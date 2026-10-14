from decimal import Decimal
from typing import Iterable, TypedDict

from django.db import transaction
from django.utils import timezone

from app_auth.permissions import no_right_message
from app_catalog.models import Deadlines, Fabric, ProductModel, Team

from .errors import ActionError, NoRight
from .models import (
    STAGE_ORDER,
    EventKind,
    FabricSlot,
    Item,
    ItemEvent,
    ItemFabric,
    Stage,
    TrashReason,
    due_date,
)
from .numbering import take_numbers

MAX_QTY = 50

NEXT = {Stage.ORDERS: Stage.CUT, Stage.CUT: Stage.COVER, Stage.COVER: Stage.WORK, Stage.WORK: Stage.FG}
MOVE_RIGHT = {
    Stage.CUT: "move_orders_cut",
    Stage.COVER: "move_cut_cover",
    Stage.WORK: "move_cover_work",
    Stage.FG: "move_work_fg",
}


class FabricInput(TypedDict, total=False):
    slot: str
    fabric: Fabric
    meters: Decimal | None


def require(user, code: str) -> None:
    if not user.has_perm(f"app_auth.{code}"):
        raise NoRight(no_right_message(code))


def stage_label(stage: str) -> str:
    return Stage(stage).label


def log(item: Item, user, kind: str, text: str, **data) -> ItemEvent:
    return ItemEvent.objects.create(item=item, user=user, kind=kind, text=text, data=data)


def lock(item_id: int) -> Item:
    try:
        return Item.objects.select_for_update().get(pk=item_id)
    except Item.DoesNotExist:
        raise ActionError("Изделие не найдено.")


def not_in_trash(item: Item) -> None:
    if item.in_trash:
        raise ActionError(f"{item.number} в Корзине — сначала восстановите его.")


def check_fabrics(fabrics: list[FabricInput]) -> list[FabricInput]:
    slots = [f["slot"] for f in fabrics]
    if len(slots) != len(set(slots)):
        raise ActionError("Каждое место ткани можно указать один раз.")
    if FabricSlot.MAIN not in slots:
        raise ActionError("Укажите основную ткань.")
    for f in fabrics:
        if f["slot"] not in FabricSlot.values:
            raise ActionError(f"Неизвестное место ткани: {f['slot']}.")
        if not f["fabric"].active:
            raise ActionError(f"Ткань «{f['fabric'].name}» скрыта из справочника.")
        if f.get("meters") is not None and f["meters"] < 0:
            raise ActionError("Метраж не может быть отрицательным.")
    return fabrics


def meters_text(meters) -> str:
    value = Decimal(str(meters)).quantize(Decimal("0.01")).normalize()
    return f"{value:f}".replace(".", ",") + " м"


def fabrics_text(fabrics: Iterable) -> str:
    order = list(FabricSlot.values)
    items = sorted(fabrics, key=lambda f: order.index(f["slot"] if isinstance(f, dict) else f.slot))
    parts = []
    for f in items:
        slot, fabric, meters = (f["slot"], f["fabric"], f.get("meters")) if isinstance(f, dict) else (f.slot, f.fabric, f.meters)
        parts.append(f"{FabricSlot(slot).label}: {fabric.name}" + (f" {meters_text(meters)}" if meters is not None else ""))
    return "; ".join(parts)


@transaction.atomic
def create_items(
    user,
    *,
    model: ProductModel,
    fabrics: list[FabricInput],
    extra: str = "",
    reserve: str = "",
    indiv: bool = False,
    indiv_note: str = "",
    comment: str = "",
    qty: int = 1,
    copy_of: Item | None = None,
) -> list[Item]:
    require(user, "edit")
    if not 1 <= qty <= MAX_QTY:
        raise ActionError(f"Количество — от 1 до {MAX_QTY}.")
    if not model.active:
        raise ActionError(f"Модель «{model.name}» скрыта из справочника.")
    check_fabrics(fabrics)

    reserve = reserve.strip()
    now = timezone.now()
    stage = Stage.ORDERS if reserve else Stage.CUT
    due = due_date(timezone.localdate(), Deadlines.get()) if indiv else None
    period, seqs = take_numbers(qty)

    items = []
    for seq in seqs:
        item = Item.objects.create(
            period=period,
            seq=seq,
            model=model,
            extra=extra.strip(),
            comment=comment.strip(),
            reserve=reserve,
            reserved_at=now if reserve else None,
            stage=stage,
            stage_since=now,
            indiv=indiv,
            indiv_note=indiv_note.strip() if indiv else "",
            due_at=due,
            manager=user,
            created_at=now,
        )
        ItemFabric.objects.bulk_create(
            [ItemFabric(item=item, slot=f["slot"], fabric=f["fabric"], meters=f.get("meters")) for f in fabrics]
        )
        text = f"Заведено → {stage_label(stage)}"
        if copy_of:
            text = f"Копия {copy_of.number} → {stage_label(stage)}"
        log(item, user, EventKind.CREATED, text, stage=stage, reserve=reserve, copy_of=copy_of.number if copy_of else None)
        items.append(item)
    return items


def _enter_stage(item: Item, to: str, team: Team | None) -> None:
    today = timezone.localdate()
    target = STAGE_ORDER.index(to)
    if target >= STAGE_ORDER.index(Stage.COVER):
        item.sew_at = item.sew_at or today
        item.cover_ready_at = item.cover_ready_at or today
    if to == Stage.WORK:
        team = team or item.team
        if team is None:
            raise ActionError(f"{item.number}: для «В работе» нужна бригада.")
        if not team.active:
            raise ActionError(f"Бригада «{team.name}» скрыта из справочника.")
        item.team = team
        item.work_at = today
    item.stage = to
    item.stage_since = timezone.now()


def _move(user, item: Item, to: str, team: Team | None) -> Item:
    not_in_trash(item)
    if to not in Stage.values:
        raise ActionError(f"Неизвестный этап: {to}.")
    if to == item.stage:
        raise ActionError(f"{item.number} уже на этапе «{stage_label(to)}».")
    if NEXT.get(item.stage) == to:
        require(user, MOVE_RIGHT[to])
    else:
        require(user, "move_any")
        if to == Stage.ORDERS:
            raise ActionError("На «Заказы» перемещать нельзя — туда попадают только новые изделия с резервом.")
    source = item.stage
    _enter_stage(item, to, team)
    item.save()
    text = f"{stage_label(source)} → {stage_label(to)}"
    if to == Stage.WORK:
        text += f", бригада {item.team.name}"
    log(item, user, EventKind.MOVE, text, source=source, to=to, team=item.team_id if to == Stage.WORK else None)
    return item


@transaction.atomic
def move(user, item_id: int, to: str, team: Team | None = None) -> Item:
    return _move(user, lock(item_id), to, team)


@transaction.atomic
def bulk_move(user, item_ids: list[int], to: str, team: Team | None = None) -> list[Item]:
    ids = sorted(set(item_ids))
    if not ids:
        raise ActionError("Не выбрано ни одного изделия.")
    items = list(Item.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if len(items) != len(ids):
        raise ActionError("Часть изделий не найдена.")
    return [_move(user, item, to, team) for item in items]


@transaction.atomic
def ship(user, item_id: int) -> Item:
    require(user, "ship")
    item = lock(item_id)
    not_in_trash(item)
    if item.stage != Stage.FG:
        raise ActionError(f"Отгрузить можно только с СГП, {item.number} на этапе «{stage_label(item.stage)}».")
    item.trashed_at = timezone.now()
    item.trash_reason = TrashReason.SHIPPED
    item.save()
    log(item, user, EventKind.SHIP, "Отгружено → Корзина")
    return item


@transaction.atomic
def trash(user, item_id: int) -> Item:
    require(user, "trash")
    item = lock(item_id)
    not_in_trash(item)
    item.trashed_at = timezone.now()
    item.trash_reason = TrashReason.DELETED
    item.save()
    log(item, user, EventKind.TRASH, f"Удалено в Корзину с этапа «{stage_label(item.stage)}»")
    return item


@transaction.atomic
def restore(user, item_id: int) -> Item:
    require(user, "restore")
    item = lock(item_id)
    if not item.in_trash:
        raise ActionError(f"{item.number} не в Корзине.")
    reason = item.get_trash_reason_display().lower()
    item.trashed_at = None
    item.trash_reason = ""
    item.save()
    log(item, user, EventKind.RESTORE, f"Восстановлено из Корзины ({reason}) → {stage_label(item.stage)}")
    return item


@transaction.atomic
def return_to_work(user, item_id: int) -> Item:
    require(user, "return_to_work")
    item = lock(item_id)
    not_in_trash(item)
    if item.stage != Stage.FG:
        raise ActionError(f"Вернуть в работу можно только с СГП, {item.number} на этапе «{stage_label(item.stage)}».")
    _enter_stage(item, Stage.WORK, None)
    item.save()
    log(item, user, EventKind.RETURN_TO_WORK, f"СГП → В работе (возврат), бригада {item.team.name}", team=item.team_id)
    return item


def _mark(user, item_id: int, stage: str, field: str, kind: str, text: str) -> Item:
    require(user, "marks")
    item = lock(item_id)
    not_in_trash(item)
    if item.stage != stage:
        raise ActionError(f"Отметка «{text}» — только на этапе «{stage_label(stage)}».")
    if getattr(item, field):
        raise ActionError(f"У {item.number} уже отмечено «{text}».")
    today = timezone.localdate()
    setattr(item, field, today)
    if field == "cover_ready_at" and not item.sew_at:
        item.sew_at = today
    item.save()
    log(item, user, kind, text, date=today.isoformat())
    return item


@transaction.atomic
def mark_fabric_arrived(user, item_id: int) -> Item:
    return _mark(user, item_id, Stage.ORDERS, "fabric_arrived_at", EventKind.FABRIC, "Ткань пришла")


@transaction.atomic
def mark_sew(user, item_id: int) -> Item:
    return _mark(user, item_id, Stage.CUT, "sew_at", EventKind.SEW, "Выдано в шитьё")


@transaction.atomic
def mark_cover_ready(user, item_id: int) -> Item:
    return _mark(user, item_id, Stage.CUT, "cover_ready_at", EventKind.COVER_READY, "Чехол готов")


@transaction.atomic
def set_reserve(user, item_id: int, reserve: str) -> Item:
    require(user, "reserve")
    item = lock(item_id)
    not_in_trash(item)
    old, new = item.reserve, (reserve or "").strip()
    if old == new:
        return item
    if not new:
        text = f"Резерв снят (был «{old}»)"
        item.reserved_at = None
    elif not old:
        text = f"Резерв: «{new}»"
        item.reserved_at = timezone.now()
    else:
        text = f"Резерв: «{old}» → «{new}»"
    item.reserve = new
    item.save()
    log(item, user, EventKind.RESERVE, text, old=old, new=new)
    return item


EDITABLE = {
    "model": "Модель",
    "extra": "Комплектация",
    "comment": "Комментарий",
    "indiv": "Индивидуальный заказ",
    "indiv_note": "Что особенного",
}


def _show(field: str, value) -> str:
    if field == "indiv":
        return "да" if value else "нет"
    if isinstance(value, ProductModel):
        return value.name
    return value or "—"


@transaction.atomic
def update_item(user, item_id: int, *, fabrics: list[FabricInput] | None = None, **fields) -> Item:
    require(user, "edit")
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise ActionError(f"Нельзя менять: {', '.join(sorted(unknown))}.")
    item = lock(item_id)
    not_in_trash(item)

    if "model" in fields and fields["model"] != item.model and not fields["model"].active:
        raise ActionError(f"Модель «{fields['model'].name}» скрыта из справочника.")
    for key in ("extra", "comment", "indiv_note"):
        if key in fields:
            fields[key] = (fields[key] or "").strip()
    if fields.get("indiv") is False:
        fields["indiv_note"] = ""

    changes = []
    for field, value in fields.items():
        old = getattr(item, field)
        if old != value:
            changes.append((field, old, value))
            setattr(item, field, value)

    if any(f == "indiv" for f, _, _ in changes):
        created = timezone.localtime(item.created_at).date()
        item.due_at = due_date(created, Deadlines.get()) if item.indiv else None

    if changes:
        item.save()
        for field, old, value in changes:
            log(
                item,
                user,
                EventKind.EDIT,
                f"{EDITABLE[field]}: {_show(field, old)} → {_show(field, value)}",
                field=field,
                old=old.pk if isinstance(old, ProductModel) else old,
                new=value.pk if isinstance(value, ProductModel) else value,
            )

    if fabrics is not None:
        check_fabrics(fabrics)
        before = fabrics_text(item.fabrics.select_related("fabric"))
        after = fabrics_text(fabrics)
        if before != after:
            item.fabrics.all().delete()
            ItemFabric.objects.bulk_create(
                [ItemFabric(item=item, slot=f["slot"], fabric=f["fabric"], meters=f.get("meters")) for f in fabrics]
            )
            log(item, user, EventKind.EDIT, f"Ткани: {before} → {after}", field="fabrics", old=before, new=after)
    return item


@transaction.atomic
def copy_item(user, item_id: int) -> Item:
    source = Item.objects.select_related("model").filter(pk=item_id).first()
    if source is None:
        raise ActionError("Изделие не найдено.")
    fabrics = [
        {"slot": f.slot, "fabric": f.fabric, "meters": f.meters} for f in source.fabrics.select_related("fabric")
    ]
    [item] = create_items(
        user,
        model=source.model,
        fabrics=fabrics,
        extra=source.extra,
        reserve=source.reserve,
        copy_of=source,
    )
    log(source, user, EventKind.COPY, f"Скопировано в {item.number}", copy=item.number)
    return item
