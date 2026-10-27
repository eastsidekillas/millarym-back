from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Callable

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date

from app_catalog.models import Deadlines, ProductModel
from app_production.models import Item, Stage, TrashReason
from app_production.queries import free_q, late_q

from .rows import Row, fabrics_text, fmt_date, item_title, meters_text, model_photo, photos, ru_key, stage_index, sewing, where


class ReportError(Exception):
    pass


@dataclass
class Column:
    key: str
    title: str
    width: int = 14
    kind: str = "text"


@dataclass
class Param:
    name: str
    label: str
    type: str
    required: bool = False
    placeholder: str = ""


@dataclass
class Summary:
    title: str
    rows: list[tuple[str, str]]


@dataclass
class Result:
    title: str
    subtitle: str
    columns: list[Column]
    rows: list[Row]
    summary: list[Summary] = field(default_factory=list)
    filename: str = ""

    def as_json(self) -> dict:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "columns": [{"key": c.key, "title": c.title, "kind": c.kind} for c in self.columns],
            "rows": [r.as_json() for r in self.rows],
            "summary": [{"title": s.title, "rows": [list(r) for r in s.rows]} for s in self.summary],
            "total": len(self.rows),
            "filename": self.filename,
        }


@dataclass
class Report:
    kind: str
    title: str
    description: str
    params: list[Param]
    build: Callable[[dict], Result]

    def as_json(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "params": [p.__dict__ for p in self.params],
        }


COL_NUMBER = Column("number", "№", 10)
COL_ITEM = Column("item", "Изделие", 36)
COL_PHOTOS = Column("photos", "Ткани (фото)", 22, "photos")
COL_FABRICS = Column("fabrics", "Ткани", 30)
COL_METERS = Column("meters", "Метраж", 9)
COL_WHERE = Column("where", "Где сейчас", 16)
COL_RESERVE = Column("reserve", "Резерв", 26)
COL_RESERVED_AT = Column("reserved_at", "Резерв с", 10)
COL_SEWING = Column("sewing", "Отшит / в шитье", 16)
COL_CREATED = Column("created", "Заведено", 10)


def base(with_purged: bool = False) -> QuerySet[Item]:
    manager = Item.all_objects if with_purged else Item.objects
    return manager.select_related("model", "team").prefetch_related("fabrics__fabric")


def today_label() -> str:
    return timezone.localdate().strftime("%d.%m.%y")


def parse_models(value: str) -> tuple[list[int], bool]:
    ids, custom = [], False
    for part in (value or "").split(","):
        part = part.strip()
        if part == "custom":
            custom = True
        elif part.isdigit():
            ids.append(int(part))
    return ids, custom


def models_q(value: str) -> Q | None:
    ids, custom = parse_models(value)
    if not ids and not custom:
        return None
    q = Q(model_id__in=ids) if ids else Q(pk__in=[])
    if custom:
        q |= Q(model__isnull=True)
    return q


def models_label(value: str) -> str:
    ids, custom = parse_models(value)
    names = list(ProductModel.objects.filter(pk__in=ids).order_by("name").values_list("name", flat=True))
    if custom:
        names.append("вне справочника")
    return ", ".join(names)


def day_range(params: dict) -> tuple:
    start, end = parse_date(params.get("from") or ""), parse_date(params.get("to") or "")
    if not start or not end:
        raise ReportError("Укажите период: с какого и по какое число.")
    if start > end:
        raise ReportError("Начало периода позже конца.")
    return (
        start,
        end,
        timezone.make_aware(datetime.combine(start, time.min)),
        timezone.make_aware(datetime.combine(end, time.max)),
    )


def not_deleted() -> Q:
    return ~Q(trash_reason=TrashReason.DELETED)


def reserve_contains(qs: QuerySet[Item], text: str) -> list[Item]:
    needle = ru_key(text)
    return [i for i in qs if needle in ru_key(i.reserve)]


def stock_row(item: Item) -> Row:
    return Row(
        item.pk,
        item.number,
        {"item": item_title(item), "number": item.number, "fabrics": fabrics_text(item), "where": where(item)},
        photos(item),
    )


def order_row(item: Item) -> Row:
    return Row(
        item.pk,
        item.number,
        {
            "number": item.number,
            "created": fmt_date(item.created_at),
            "item": item_title(item),
            "fabrics": fabrics_text(item),
            "meters": meters_text(item),
            "reserve": item.reserve,
            "reserved_at": fmt_date(item.reserved_at),
            "where": where(item),
        },
        photos(item),
    )


def free_stock(params: dict) -> Result:
    qs = base().filter(free_q())
    q = models_q(params.get("models", ""))
    if q is not None:
        qs = qs.filter(q)
    items = sorted(qs, key=lambda i: (ru_key(i.title), ru_key(i.extra), stage_index(i), i.period, i.seq))
    label = models_label(params.get("models", ""))
    name = f"Свободные {label}" if label and "," not in label else "Свободные остатки"
    by_title = Counter(i.title for i in items)
    rows = []
    for i in items:
        row = stock_row(i)
        row.group = f"{i.title}: {by_title[i.title]} шт."
        row.group_photo = model_photo(i)
        rows.append(row)
    return Result(
        "Свободные остатки",
        label or "Все модели",
        [COL_ITEM, COL_NUMBER, COL_PHOTOS, COL_FABRICS, COL_WHERE],
        rows,
        filename=f"{name} {today_label()}",
    )


def revision(params: dict) -> Result:
    """Все изделия на всех этапах — для сверки со складом: по алфавиту, группы по модели."""
    items = sorted(
        base().filter(trashed_at__isnull=True),
        key=lambda i: (ru_key(i.title), ru_key(i.extra), stage_index(i), i.period, i.seq),
    )
    by_title = Counter(i.title for i in items)
    rows = []
    for i in items:
        row = stock_row(i)
        row.cells["meters"] = meters_text(i)
        row.cells["reserve"] = i.reserve or "свободно"
        row.group = f"{i.title}: {by_title[i.title]} шт."
        rows.append(row)
    by_stage = Counter(where(i) for i in items)
    free = sum(1 for i in items if not i.reserve)
    summary = [
        Summary("Итого", [("Всего изделий", str(len(items))), ("В резерве", str(len(items) - free)), ("Свободных", str(free))]),
        Summary("По этапам", [(label, str(by_stage[label])) for label in Stage.labels if by_stage[label]]),
    ]
    return Result(
        "Ревизия: все изделия",
        f"Все этапы, в резерве и свободные, на {today_label()}",
        [COL_ITEM, COL_NUMBER, COL_FABRICS, COL_METERS, COL_RESERVE, COL_WHERE],
        rows,
        summary,
        filename=f"Ревизия {today_label()}",
    )


def reserved(params: dict) -> Result:
    text = (params.get("q") or "").strip()
    qs = base().filter(trashed_at__isnull=True).exclude(reserve="")
    only_fg = params.get("only_fg") in ("1", "true")
    if only_fg:
        qs = qs.filter(stage=Stage.FG)
    items = sorted(reserve_contains(qs, text), key=lambda i: (ru_key(i.reserve), i.period, i.seq))

    same = Counter((ru_key(i.reserve), ru_key(item_title(i)), fabrics_text(i)) for i in items)
    groups: dict[str, Counter] = defaultdict(Counter)
    for i in items:
        groups[i.reserve][item_title(i)] += 1
    rows = []
    for i in items:
        row = order_row(i)
        row.cells["sewing"] = sewing(i)
        row.group = f"{i.reserve}: {sum(groups[i.reserve].values())} шт."
        if same[(ru_key(i.reserve), ru_key(item_title(i)), fabrics_text(i))] > 1:
            row.mark = "warn"
        rows.append(row)
    summary = [
        Summary(f"{reserve}: {sum(c.values())} шт.", sorted(((t, str(n)) for t, n in c.items()), key=lambda r: ru_key(r[0])))
        for reserve, c in sorted(groups.items(), key=lambda g: ru_key(g[0]))
    ]
    parts = [f"резерв содержит «{text}»" if text else "все с резервом"]
    if only_fg:
        parts.append("только СГП")
    return Result(
        "Зарезервированные изделия",
        ", ".join(parts).capitalize(),
        [COL_NUMBER, COL_ITEM, COL_PHOTOS, COL_FABRICS, COL_WHERE, COL_SEWING, COL_RESERVED_AT],
        rows,
        summary,
        filename=f"Резерв {text or 'все'} {today_label()}",
    )


def orders_period(params: dict) -> Result:
    start, end, since, until = day_range(params)
    qs = base(with_purged=True).exclude(reserve="").filter(not_deleted(), created_at__range=(since, until)).order_by("created_at")
    return Result(
        "Заказы за период",
        f"Заведены с {fmt_date(start)} по {fmt_date(end)}",
        [COL_NUMBER, COL_CREATED, COL_ITEM, COL_PHOTOS, COL_FABRICS, COL_METERS, COL_RESERVE, COL_WHERE],
        [order_row(i) for i in qs],
        filename=f"Заказы {fmt_date(start)}-{fmt_date(end)}",
    )


def orders_by_reserve(params: dict) -> Result:
    text = (params.get("q") or "").strip()
    if not text:
        raise ReportError("Впишите контрагента или часть текста резерва.")
    qs = base(with_purged=True).filter(not_deleted()).exclude(reserve="")
    items = sorted(reserve_contains(qs, text), key=lambda i: (ru_key(i.reserve), i.period, i.seq))
    return Result(
        "Заказы по контрагенту",
        f"Резерв содержит «{text}», включая отгруженные",
        [COL_NUMBER, COL_CREATED, COL_ITEM, COL_PHOTOS, COL_FABRICS, COL_METERS, COL_RESERVE, COL_WHERE],
        [order_row(i) for i in items],
        filename=f"Заказы {text} {today_label()}",
    )


def title_matches(item: Item, words: list[str]) -> bool:
    title = ru_key(item.title)
    return any(word in title for word in words)


def orders_by_model(params: dict) -> Result:
    words = [ru_key(w.strip()) for w in (params.get("q") or "").split(",") if w.strip()]
    if not words:
        raise ReportError("Впишите название изделия или его часть.")
    qs = base(with_purged=True).exclude(reserve="").filter(not_deleted())
    items = sorted((i for i in qs if title_matches(i, words)), key=lambda i: (ru_key(i.title), i.period, i.seq))
    text = ", ".join(w.strip() for w in params["q"].split(",") if w.strip())
    return Result(
        "Заказы по модели",
        f"Название содержит «{text}», включая отгруженные",
        [COL_NUMBER, COL_CREATED, COL_ITEM, COL_PHOTOS, COL_FABRICS, COL_METERS, COL_RESERVE, COL_WHERE],
        [order_row(i) for i in items],
        filename=f"Заказы {text} {today_label()}",
    )


def no_fabric(params: dict) -> Result:
    d = Deadlines.get()
    today = timezone.localdate()
    qs = base().filter(stage=Stage.ORDERS, fabric_arrived_at__isnull=True, trashed_at__isnull=True).order_by("created_at")
    rows = []
    for i in qs:
        days = (today - timezone.localtime(i.created_at).date()).days
        late = i.indiv and days > d.fabric_days
        rows.append(
            Row(
                i.pk,
                i.number,
                {
                    "number": i.number,
                    "item": item_title(i),
                    "fabrics": fabrics_text(i),
                    "reserve": i.reserve,
                    "created": fmt_date(i.created_at),
                    "ordered": fmt_date(i.fabric_ordered_at) if i.fabric_ordered_at else "не заказана",
                    "days": str(days),
                    "late": "просрочено" if late else ("индивидуальный" if i.indiv else ""),
                },
                mark="crit" if late else "",
            )
        )
    return Result(
        "Заказы, на которые не пришла ткань",
        f"Просрок считается только у индивидуальных: больше {d.fabric_days} дн.",
        [
            COL_NUMBER, COL_ITEM, COL_FABRICS, COL_RESERVE, COL_CREATED, Column("ordered", "Ткань заказана", 12),
            Column("days", "Ждём, дн.", 10, "number"), Column("late", "Срок", 14),
        ],
        rows,
        filename=f"Не пришла ткань {today_label()}",
    )


WARNING_TEXT = {"fabric": "ткань", "cut": "крой", "output": "выпуск"}


def overdue(params: dict) -> Result:
    d = Deadlines.get()
    today = timezone.localdate()
    qs = base().filter(late_q(d, today)).order_by("created_at")
    rows = []
    for i in qs:
        days = (today - timezone.localtime(i.created_at).date()).days
        what = ", ".join(WARNING_TEXT[w] for w in i.warnings(today, d))
        rows.append(
            Row(
                i.pk,
                i.number,
                {
                    "number": i.number,
                    "item": item_title(i),
                    "reserve": i.reserve,
                    "where": where(i),
                    "what": what,
                    "days": str(days),
                    "due": fmt_date(i.due_at),
                },
                mark="crit",
            )
        )
    return Result(
        "Заказы с просроком",
        f"Индивидуальные: ткань больше {d.fabric_days} дн., крой больше {d.cut_days} дн., выпуск больше {d.output_days} дн.",
        [COL_NUMBER, COL_ITEM, COL_RESERVE, COL_WHERE, Column("what", "Что просрочено", 16),
         Column("days", "Дней с заведения", 10, "number"), Column("due", "Срок", 10)],
        rows,
        filename=f"Просрок {today_label()}",
    )


def single_item(item: Item) -> Result:
    return Result(
        f"Изделие {item.number}",
        item.reserve or "Свободно",
        [COL_ITEM, COL_NUMBER, COL_PHOTOS, COL_FABRICS, COL_WHERE],
        [stock_row(item)],
        filename=f"Изделие {item.number.replace('/', '-')}",
    )


def claims_report(params: dict) -> Result:
    from app_claims.models import Claim, DefectType
    from app_claims.queries import filter_claims

    start, end, _, _ = day_range(params)
    qs = filter_claims(Claim.objects.select_related("manager"), {"from": params.get("from"), "to": params.get("to")})
    order = {value: i for i, value in enumerate(DefectType.values)}
    claims = sorted(qs, key=lambda c: (order.get(c.defect_type, len(order)), c.period, c.seq))
    by_defect = Counter(c.get_defect_type_display() or "Не указан" for c in claims)
    by_type = Counter(c.get_claim_type_display() for c in claims)
    by_state = Counter(c.get_state_display() for c in claims)
    rows = []
    for c in claims:
        label = c.get_defect_type_display() or "Не указан"
        rows.append(
            Row(
                c.pk,
                c.number,
                {
                    "act": c.number,
                    "date": fmt_date(c.act_date or c.created_at),
                    "counterparty": c.counterparty,
                    "item": c.product,
                    "item_number": c.item_number,
                    "type": c.get_claim_type_display(),
                    "state": c.get_state_display() + (f" {fmt_date(c.closed_at)}" if c.closed_at else ""),
                    "description": c.description,
                },
                group=f"{label}: {by_defect[label]} шт.",
            )
        )
    summary = [
        Summary("По виду дефекта", [(k, str(v)) for k, v in by_defect.most_common()]),
        Summary("По типу претензии", [(k, str(v)) for k, v in by_type.most_common()]),
        Summary("По состоянию", [(k, str(v)) for k, v in by_state.most_common()]),
    ]
    return Result(
        "Рекламации",
        f"Заведены с {fmt_date(start)} по {fmt_date(end)}",
        [Column("act", "№ акта", 9), Column("date", "Дата", 10), Column("counterparty", "Контрагент", 24),
         Column("item", "Изделие", 30), Column("item_number", "№ изделия", 12), Column("type", "Тип претензии", 16),
         Column("state", "Состояние", 18), Column("description", "Описание", 40)],
        rows,
        summary,
        filename=f"Рекламации {fmt_date(start)}-{fmt_date(end)}",
    )


MODELS_PARAM = Param("models", "Модели", "models")
REPORTS = [
    Report("free-stock", "Свободные остатки", "Все изделия без резерва на Крое, Складе чехлов, В работе и СГП, с фото тканей. Можно выбрать модели.", [MODELS_PARAM], free_stock),
    Report("reserved", "Зарезервированные по контрагенту", "Все подписанные изделия на любом этапе: итог по моделям для сверки с заявкой, повторы подсвечены. Годится для погрузки.", [Param("q", "Контрагент или часть резерва", "text", placeholder="Пусто — все контрагенты"), Param("only_fg", "Только СГП", "bool")], reserved),
    Report("revision", "Ревизия: все изделия", "Все изделия на всех этапах — заказы, в резерве и свободные — по алфавиту моделей, с количеством по каждой модели. Для сверки со складом.", [], revision),
    Report("orders-period", "Заказы за период", "Изделия с резервом, заведённые в эти даты, включая отгруженные.", [Param("from", "С", "date", True), Param("to", "По", "date", True)], orders_period),
    Report("orders-by-reserve", "Заказы по контрагенту", "Все изделия, у которых резерв содержит текст, включая отгруженные.", [Param("q", "Контрагент или часть резерва", "text", True, "Например, Фоминых")], orders_by_reserve),
    Report("orders-by-model", "Заказы по модели", "Изделия с резервом, в названии которых есть этот текст: «Бали» найдёт и «Бали (4 кат.)», и спецзаказы, вписанные вручную. Несколько — через запятую. Включая отгруженные.", [Param("q", "Название изделия или его часть", "text", True, "Например, Бали или Бали, Бостон")], orders_by_model),
    Report("no-fabric", "Не пришла ткань", "Все заказы на этапе «Заказы» без отметки «Ткань пришла»: заказана ли ткань и сколько дней ждём.", [], no_fabric),
    Report("claims", "Рекламации", "Рекламации, заведённые за период, по виду дефекта: сколько пришло с каждой проблемой, итог по типу претензии.", [Param("from", "С", "date", True), Param("to", "По", "date", True)], claims_report),
    Report("overdue", "Заказы с просроком", "Индивидуальные заказы с просрочкой по ткани, крою или выпуску.", [], overdue),
]
BY_KIND = {r.kind: r for r in REPORTS}


def free_stock_models() -> list[dict]:
    counts = Counter()
    names = {}
    for model_id, title in Item.objects.filter(free_q()).values_list("model_id", "model__name"):
        key = model_id or "custom"
        counts[key] += 1
        names[key] = title or "Вне справочника"
    rows = [{"id": key, "name": names[key], "count": n} for key, n in counts.items()]
    return sorted(rows, key=lambda r: (r["id"] == "custom", ru_key(r["name"])))
