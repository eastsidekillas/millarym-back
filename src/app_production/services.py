from datetime import datetime, time
from decimal import Decimal
from typing import Iterable, TypedDict

from django.db import transaction
from django.utils import timezone

from app_auth.permissions import no_right_message
from app_catalog.models import Deadlines, Fabric, ProductModel, Team

from .errors import ActionError, NoRight
from .models import (
    STAGE_ORDER,
    AmountUnit,
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
    unit: str


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


def check_name(model: ProductModel | None, custom_name: str, current: ProductModel | None = None):
    custom_name = (custom_name or "").strip()
    if model is not None:
        if not model.active and model != current:
            raise ActionError(f"Модель «{model.name}» скрыта из справочника.")
        return model, ""
    if not custom_name:
        raise ActionError("Выберите модель из справочника или впишите название вручную.")
    return None, custom_name


def check_fabrics(fabrics: list[FabricInput], keep_hidden: set[int] = frozenset()) -> list[FabricInput]:
    """keep_hidden — ткани, которые уже стоят у изделия: скрытая ткань (например, заведённая переносом)
    не мешает поправить метраж или комплектацию."""
    slots = [f["slot"] for f in fabrics]
    if len(slots) != len(set(slots)):
        raise ActionError("Каждое место ткани можно указать один раз.")
    if FabricSlot.MAIN not in slots:
        raise ActionError("Укажите основную ткань.")
    for f in fabrics:
        if f["slot"] not in FabricSlot.values:
            raise ActionError(f"Неизвестное место ткани: {f['slot']}.")
        if not f["fabric"].active and f["fabric"].pk not in keep_hidden:
            raise ActionError(f"Ткань «{f['fabric'].name}» скрыта из справочника.")
        if f.get("meters") is not None and f["meters"] < 0:
            raise ActionError("Метраж не может быть отрицательным.")
        check_unit(f["slot"], f.get("unit") or AmountUnit.METERS)
    return fabrics


def check_unit(slot: str, unit: str) -> None:
    if unit not in AmountUnit.values:
        raise ActionError(f"Неизвестная единица: {unit}.")
    if unit == AmountUnit.PIECES and slot == FabricSlot.MAIN:
        raise ActionError("Основная ткань — только в метрах; в штуках можно указать компаньонов.")


def meters_text(meters, unit: str = AmountUnit.METERS) -> str:
    value = Decimal(str(meters)).quantize(Decimal("0.01")).normalize()
    return f"{value:f}".replace(".", ",") + (" шт" if unit == AmountUnit.PIECES else " м")


def fabrics_text(fabrics: Iterable) -> str:
    order = list(FabricSlot.values)
    items = sorted(fabrics, key=lambda f: order.index(f["slot"] if isinstance(f, dict) else f.slot))
    parts = []
    for f in items:
        if isinstance(f, dict):
            slot, fabric, meters, unit = f["slot"], f["fabric"], f.get("meters"), f.get("unit") or AmountUnit.METERS
        else:
            slot, fabric, meters, unit = f.slot, f.fabric, f.meters, f.unit
        parts.append(f"{FabricSlot(slot).label}: {fabric.name}" + (f" {meters_text(meters, unit)}" if meters is not None else ""))
    return "; ".join(parts)


@transaction.atomic
def create_items(
    user,
    *,
    fabrics: list[FabricInput],
    model: ProductModel | None = None,
    custom_name: str = "",
    extra: str = "",
    reserve: str = "",
    indiv: bool = False,
    indiv_note: str = "",
    comment: str = "",
    table_no: str = "",
    qty: int = 1,
    copy_of: Item | None = None,
) -> list[Item]:
    require(user, "edit")
    if not 1 <= qty <= MAX_QTY:
        raise ActionError(f"Количество — от 1 до {MAX_QTY}.")
    model, custom_name = check_name(model, custom_name)
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
            custom_name=custom_name,
            extra=extra.strip(),
            comment=comment.strip(),
            table_no=table_no.strip(),
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
            [
                ItemFabric(item=item, slot=f["slot"], fabric=f["fabric"], meters=f.get("meters"), unit=f.get("unit") or AmountUnit.METERS)
                for f in fabrics
            ]
        )
        text = f"Заведено → {stage_label(stage)}"
        if copy_of:
            text = f"Копия {copy_of.number} → {stage_label(stage)}"
        log(item, user, EventKind.CREATED, text, stage=stage, reserve=reserve, copy_of=copy_of.number if copy_of else None)
        items.append(item)
    return items


# этапы, на которые переводят с датой: кнопку жмут не в тот день, когда чехлы сдали на склад, выдали в работу, перевели на СГП
DATED = {Stage.COVER: "на склад чехлов", Stage.WORK: "в работу", Stage.FG: "на СГП"}


def _enter_stage(item: Item, to: str, team: Team | None, day=None) -> None:
    today = timezone.localdate()
    day = day or today
    target = STAGE_ORDER.index(to)
    if target >= STAGE_ORDER.index(Stage.COVER):
        # чехол на складе — значит, выдан в шитьё и отшит не позже этого дня
        mark = day if to == Stage.COVER else today
        item.sew_at = item.sew_at or mark
        item.cover_ready_at = item.cover_ready_at or mark
    if to == Stage.WORK:
        team = team or item.team
        if team is None:
            raise ActionError(f"{item.number}: для «В работе» нужна бригада.")
        if not team.active:
            raise ActionError(f"Бригада «{team.name}» скрыта из справочника.")
        item.team = team
        item.work_at = day
    if to == Stage.FG:
        item.fg_at = day
    item.stage = to
    item.stage_since = timezone.now() if day == today else timezone.make_aware(datetime.combine(day, time(12)))


def check_move_date(item: Item, to: str, day) -> None:
    """Дата перевода: не в будущем, не раньше заведения и не раньше, чем изделие попало на нынешний этап."""
    where = DATED.get(to, f"на «{stage_label(to)}»")
    if day > timezone.localdate():
        raise ActionError(f"Дата перевода {where} не может быть позже сегодняшней.")
    created = timezone.localtime(item.created_at).date()
    if day < created:
        raise ActionError(f"{item.number}: дата перевода {where} раньше, чем заведено изделие ({created:%d.%m.%y}).")
    if to == Stage.FG and item.work_at and day < item.work_at:
        raise ActionError(f"{item.number}: дата СГП раньше выдачи в работу ({item.work_at:%d.%m.%y}).")
    if to == Stage.WORK and item.stage == Stage.COVER:
        since = timezone.localtime(item.stage_since).date()
        if day < since:
            raise ActionError(f"{item.number}: дата выдачи в работу раньше, чем чехол попал на склад ({since:%d.%m.%y}).")
    if to == Stage.COVER and item.cover_ready_at and day < item.cover_ready_at:
        raise ActionError(f"{item.number}: дата перевода на склад чехлов раньше «Отшит» ({item.cover_ready_at:%d.%m.%y}).")


def check_fg_date(item: Item, day) -> None:
    check_move_date(item, Stage.FG, day)


def _move(user, item: Item, to: str, team: Team | None, day=None) -> Item:
    not_in_trash(item)
    if to not in Stage.values:
        raise ActionError(f"Неизвестный этап: {to}.")
    if to == item.stage:
        raise ActionError(f"{item.number} уже на этапе «{stage_label(to)}».")
    if NEXT.get(item.stage) == to:
        require(user, MOVE_RIGHT[to])
    else:
        require(user, "move_any")
        # назад на «Заказы» — если по ошибке нажали «В крой»: там отмечают заказ ткани
        if to == Stage.ORDERS and not item.reserve:
            raise ActionError(f"{item.number} без резерва — на «Заказы» попадают только изделия с резервом. Сначала впишите резерв.")
    day = day if to in DATED else None
    if day:
        check_move_date(item, to, day)
    source = item.stage
    _enter_stage(item, to, team, day)
    item.save()
    text = f"{stage_label(source)} → {stage_label(to)}"
    if to == Stage.WORK:
        text += f", бригада {item.team.name}"
    if day and day != timezone.localdate():
        text += f", дата {day:%d.%m.%y}"
    log(item, user, EventKind.MOVE, text, source=source, to=to, team=item.team_id if to == Stage.WORK else None)
    return item


@transaction.atomic
def move(user, item_id: int, to: str, team: Team | None = None, day=None) -> Item:
    return _move(user, lock(item_id), to, team, day)


@transaction.atomic
def bulk_move(user, item_ids: list[int], to: str, team: Team | None = None, day=None) -> list[Item]:
    ids = sorted(set(item_ids))
    if not ids:
        raise ActionError("Не выбрано ни одного изделия.")
    items = list(Item.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if len(items) != len(ids):
        raise ActionError("Часть изделий не найдена.")
    return [_move(user, item, to, team, day) for item in items]


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
def ack_changes(user, item_id: int) -> Item:
    """Цех увидел правку изделия — отметка «изменено» в списке снимается."""
    item = lock(item_id)
    if item.changed_at is None:
        return item
    item.changed_at = None
    item.save(update_fields=["changed_at"])
    log(item, user, EventKind.EDIT, "Изменения учтены", field="ack")
    return item


@transaction.atomic
def cancel_order(user, item_id: int) -> Item:
    """Клиент передумал до кроя: изделие уходит в Корзину с причиной «Заказ снят»."""
    require(user, "edit")
    item = lock(item_id)
    not_in_trash(item)
    if item.stage != Stage.ORDERS:
        raise ActionError(
            f"{item.number} уже на этапе «{stage_label(item.stage)}». Снять заказ можно только на «Заказах»; "
            "дальше уберите резерв — изделие станет свободным."
        )
    item.trashed_at = timezone.now()
    item.trash_reason = TrashReason.CANCELLED
    item.save()
    log(item, user, EventKind.TRASH, f"Заказ снят (резерв был «{item.reserve}»)" if item.reserve else "Заказ снят")
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


MARKS = {
    "fabric_ordered": (Stage.ORDERS, "fabric_ordered_at", EventKind.FABRIC_ORDERED, "Ткань заказана"),
    "fabric_arrived": (Stage.ORDERS, "fabric_arrived_at", EventKind.FABRIC, "Ткань пришла"),
    "sew": (Stage.CUT, "sew_at", EventKind.SEW, "Выдано в шитьё"),
    "cover_ready": (Stage.CUT, "cover_ready_at", EventKind.COVER_READY, "Отшит"),
    # только для правки даты; снять нельзя — для этого «Исправить этап…»
    "work": (Stage.WORK, "work_at", EventKind.MOVE, "Выдано в работу"),
    "fg": (Stage.FG, "fg_at", EventKind.MOVE, "На СГП"),
}
MARK_RIGHT = {"work": MOVE_RIGHT[Stage.WORK], "fg": MOVE_RIGHT[Stage.FG]}


@transaction.atomic
def set_mark_date(user, item_id: int, mark: str, day) -> Item:
    """Поправить дату отметки: кнопку нажали не в тот день, когда ткань пришла или чехол отшили."""
    if mark not in MARKS:
        raise ActionError("Неизвестная отметка.")
    _, field, kind, text = MARKS[mark]
    require(user, MARK_RIGHT.get(mark, "marks"))
    item = lock(item_id)
    not_in_trash(item)
    old = getattr(item, field)
    if not old:
        raise ActionError(f"У {item.number} не отмечено «{text}» — сначала поставьте отметку.")
    if day == old:
        return item
    if day > timezone.localdate():
        raise ActionError("Дата не может быть позже сегодняшней.")
    created = timezone.localtime(item.created_at).date()
    if day < created:
        raise ActionError(f"Дата не может быть раньше, чем заведено изделие ({created:%d.%m.%y}).")
    if mark == "cover_ready" and item.sew_at:
        if item.sew_at == old:
            # «В шитьё» поставилось само вместе с «Отшит» — двигаем вместе
            item.sew_at = day
        elif day < item.sew_at:
            raise ActionError(f"«Отшит» не может быть раньше «Выдано в шитьё» ({item.sew_at:%d.%m.%y}).")
    if mark == "sew" and item.cover_ready_at and day > item.cover_ready_at:
        raise ActionError(f"«Выдано в шитьё» не может быть позже «Отшит» ({item.cover_ready_at:%d.%m.%y}).")
    if mark == "fg":
        check_fg_date(item, day)
    if mark == "work" and item.fg_at and day > item.fg_at:
        raise ActionError(f"«Выдано в работу» не может быть позже «На СГП» ({item.fg_at:%d.%m.%y}).")
    if mark in MARK_RIGHT and item.stage == MARKS[mark][0]:
        item.stage_since = timezone.make_aware(datetime.combine(day, time(12)))
    if mark == "fabric_arrived" and item.fabric_ordered_at and day < item.fabric_ordered_at:
        raise ActionError(f"«Ткань пришла» не может быть раньше «Ткань заказана» ({item.fabric_ordered_at:%d.%m.%y}).")
    if mark == "fabric_ordered" and item.fabric_arrived_at and day > item.fabric_arrived_at:
        raise ActionError(f"«Ткань заказана» не может быть позже «Ткань пришла» ({item.fabric_arrived_at:%d.%m.%y}).")
    setattr(item, field, day)
    item.save()
    log(item, user, kind, f"Дата «{text}»: {old:%d.%m.%y} → {day:%d.%m.%y}", date=day.isoformat())
    return item


@transaction.atomic
def unmark(user, item_id: int, mark: str) -> Item:
    """Снять отметку, поставленную по ошибке, пока изделие на том же этапе."""
    if mark not in MARKS or mark == "fg":
        raise ActionError("Неизвестная отметка.")
    stage, field, kind, text = MARKS[mark]
    require(user, "marks")
    item = lock(item_id)
    not_in_trash(item)
    if item.stage != stage:
        raise ActionError(f"Снять «{text}» можно только на этапе «{stage_label(stage)}».")
    if not getattr(item, field):
        raise ActionError(f"У {item.number} не отмечено «{text}».")
    if mark == "sew" and item.cover_ready_at:
        raise ActionError("Сначала снимите отметку «Отшит».")
    was = getattr(item, field)
    setattr(item, field, None)
    item.save()
    log(item, user, kind, f"Отметка «{text}» снята (была {was:%d.%m.%y})", undo=True)
    return item


@transaction.atomic
def mark_fabric_ordered(user, item_id: int) -> Item:
    return _mark(user, item_id, Stage.ORDERS, "fabric_ordered_at", EventKind.FABRIC_ORDERED, "Ткань заказана")


@transaction.atomic
def mark_fabric_arrived(user, item_id: int) -> Item:
    return _mark(user, item_id, Stage.ORDERS, "fabric_arrived_at", EventKind.FABRIC, "Ткань пришла")


@transaction.atomic
def mark_sew(user, item_id: int) -> Item:
    return _mark(user, item_id, Stage.CUT, "sew_at", EventKind.SEW, "Выдано в шитьё")


@transaction.atomic
def mark_cover_ready(user, item_id: int) -> Item:
    return _mark(user, item_id, Stage.CUT, "cover_ready_at", EventKind.COVER_READY, "Отшит")


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
    "extra": "Комплектация",
    "comment": "Комментарий",
    "table_no": "Номер стола",
    "indiv": "Индивидуальный заказ",
    "indiv_note": "Что особенного",
}


def _show(field: str, value) -> str:
    if field == "indiv":
        return "да" if value else "нет"
    return value or "—"


@transaction.atomic
def update_item(
    user,
    item_id: int,
    *,
    fabrics: list[FabricInput] | None = None,
    model: ProductModel | None | object = ...,
    custom_name: str | None = None,
    **fields,
) -> Item:
    require(user, "edit")
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise ActionError(f"Нельзя менять: {', '.join(sorted(unknown))}.")
    item = lock(item_id)
    not_in_trash(item)

    if model is not ... or custom_name is not None:
        new_model = item.model if model is ... else model
        new_custom = item.custom_name if custom_name is None else custom_name
        new_model, new_custom = check_name(new_model, new_custom, current=item.model)
        old = (item.model_id, item.custom_name, item.title)
        item.model, item.custom_name = new_model, new_custom
        if (item.model_id, item.custom_name) != old[:2]:
            item.changed_at = timezone.now()
            item.save()
            title = item.title if item.model_id else f"{item.title} (вне справочника)"
            log(item, user, EventKind.EDIT, f"Название: {old[2]} → {title}", field="name", old=old[2], new=item.title)

    for key in ("extra", "comment", "indiv_note", "table_no"):
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
        if any(f != "comment" for f, _, _ in changes):
            item.changed_at = timezone.now()
        item.save()
        for field, old, value in changes:
            log(
                item,
                user,
                EventKind.EDIT,
                f"{EDITABLE[field]}: {_show(field, old)} → {_show(field, value)}",
                field=field,
                old=old,
                new=value,
            )

    if fabrics is not None:
        check_fabrics(fabrics, keep_hidden=set(item.fabrics.values_list("fabric_id", flat=True)))
        before = fabrics_text(item.fabrics.select_related("fabric"))
        after = fabrics_text(fabrics)
        if before != after:
            item.fabrics.all().delete()
            ItemFabric.objects.bulk_create(
                [
                ItemFabric(item=item, slot=f["slot"], fabric=f["fabric"], meters=f.get("meters"), unit=f.get("unit") or AmountUnit.METERS)
                for f in fabrics
            ]
            )
            item.changed_at = timezone.now()
            item.save(update_fields=["changed_at"])
            log(item, user, EventKind.EDIT, f"Ткани: {before} → {after}", field="fabrics", old=before, new=after)
    return item


@transaction.atomic
def set_fabric_amount(user, item_id: int, slot: str, meters, unit: str = AmountUnit.METERS) -> Item:
    """Метраж (или штуки у компаньона) в любой момент: менеджер при заведении его часто не знает,
    вписывает руководитель закройного цеха. Право — «Изделия» или «Отметки»."""
    if not (user.has_perm("app_auth.edit") or user.has_perm("app_auth.marks")):
        raise NoRight(no_right_message("marks"))
    item = lock(item_id)
    not_in_trash(item)
    row = item.fabrics.select_related("fabric").filter(slot=slot).first()
    if row is None:
        raise ActionError(f"У {item.number} нет ткани «{FabricSlot(slot).label if slot in FabricSlot.values else slot}».")
    if meters is not None and meters < 0:
        raise ActionError("Метраж не может быть отрицательным.")
    check_unit(slot, unit)
    before = fabrics_text([row])
    if (row.meters, row.unit) == (meters, unit):
        return item
    row.meters, row.unit = meters, unit
    row.save(update_fields=["meters", "unit"])
    after = fabrics_text([row])
    log(item, user, EventKind.EDIT, f"Ткани: {before} → {after}", field="fabrics", old=before, new=after)
    return item


@transaction.atomic
def copy_item(user, item_id: int) -> Item:
    source = Item.objects.select_related("model").filter(pk=item_id).first()
    if source is None:
        raise ActionError("Изделие не найдено.")
    fabrics = [
        {"slot": f.slot, "fabric": f.fabric, "meters": f.meters, "unit": f.unit} for f in source.fabrics.select_related("fabric")
    ]
    [item] = create_items(
        user,
        model=source.model,
        custom_name=source.custom_name,
        fabrics=fabrics,
        extra=source.extra,
        reserve=source.reserve,
        copy_of=source,
    )
    log(source, user, EventKind.COPY, f"Скопировано в {item.number}", copy=item.number)
    return item


def purge_trash(today=None) -> list[str]:
    due = Item.objects.due_for_purge(today)
    numbers = list(due.order_by("period", "seq").values_list("number", flat=True))
    due.update(purged_at=timezone.now())
    return numbers
