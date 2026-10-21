import re
from datetime import datetime, time, timedelta

from django.db.models import Count, F, Q, QuerySet, Value
from django.db.models.functions import Coalesce, Lower, Replace
from django.utils import timezone

from app_catalog.models import Deadlines

from .models import STAGE_ORDER, Item, Stage

TRASH = "trash"
STAGE_FILTERS = [*Stage.values, TRASH]
ORDERINGS = {
    "recent": ["-stage_since", "-id"],
    "number": ["period", "seq"],
    "-number": ["-period", "-seq"],
    "created": ["created_at", "id"],
    "-created": ["-created_at", "-id"],
    "model": ["model__name", "custom_name", "period", "seq"],
    "alpha": ["title_key", "extra_key", "period", "seq"],
    "trashed": ["-trashed_at", "-id"],
}

FULL_NUMBER = re.compile(r"^\d{2}/\d+$")
SHORT_NUMBER = re.compile(r"^\d{1,5}$")


def _day_start(day) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def late_q(deadlines: Deadlines | None = None, today=None) -> Q:
    d = deadlines or Deadlines.get()
    today = today or timezone.localdate()
    fabric = Q(
        stage=Stage.ORDERS,
        fabric_arrived_at__isnull=True,
        created_at__lt=_day_start(today - timedelta(days=d.fabric_days)),
    )
    cut = Q(
        stage__in=[Stage.ORDERS, Stage.CUT],
        cover_ready_at__isnull=True,
        created_at__lt=_day_start(today - timedelta(days=d.cut_days)),
    )
    output = Q(due_at__lt=today)
    return Q(indiv=True, trashed_at__isnull=True) & ~Q(stage=Stage.FG) & (fabric | cut | output)


def free_q() -> Q:
    return Q(reserve="", trashed_at__isnull=True) & ~Q(stage=Stage.ORDERS)


def search_q(text: str) -> Q:
    text = text.strip()
    if FULL_NUMBER.match(text):
        year, seq = text.split("/")
        return Q(period=2000 + int(year), seq=int(seq))
    q = (
        Q(model__name__icontains=text)
        | Q(custom_name__icontains=text)
        | Q(extra__icontains=text)
        | Q(reserve__icontains=text)
        | Q(comment__icontains=text)
        | Q(fabrics__fabric__name__icontains=text)
        | Q(legacy_number__icontains=text)
        | Q(team__name__icontains=text)
    )
    if SHORT_NUMBER.match(text):
        q |= Q(seq=int(text))
    return q


def base_queryset() -> QuerySet[Item]:
    return Item.objects.select_related("model", "model__category", "team", "manager").prefetch_related(
        "fabrics__fabric"
    )


def default_ordering(stage: str) -> str:
    """«Заказы» — по дате, Крой, Склад чехлов, В работе, СГП — по алфавиту изделий."""
    if stage == TRASH:
        return "trashed"
    if stage in (Stage.CUT, Stage.COVER, Stage.WORK, Stage.FG):
        return "alpha"
    return "recent"


def alpha_key(expr):
    return Replace(Lower(expr), Value("ё"), Value("е"))


def filter_items(qs: QuerySet[Item], params) -> QuerySet[Item]:
    stage = params.get("stage") or ""
    text = (params.get("q") or "").strip()

    if stage == TRASH:
        qs = qs.filter(trashed_at__isnull=False)
    elif stage:
        qs = qs.filter(stage=stage, trashed_at__isnull=True)
    elif not text:
        qs = qs.filter(trashed_at__isnull=True)

    if text:
        ids = Item.objects.filter(search_q(text)).values("pk")
        qs = qs.filter(pk__in=ids)
    if params.get("free") in ("1", "true"):
        qs = qs.filter(free_q())
    if params.get("reserved") in ("1", "true"):
        qs = qs.exclude(reserve="")
    if params.get("indiv") in ("1", "true"):
        qs = qs.filter(indiv=True)
    if params.get("late") in ("1", "true"):
        qs = qs.filter(late_q())
    models = [m for m in (params.get("model") or "").split(",") if m.strip().isdigit()]
    if models:
        qs = qs.filter(model_id__in=[int(m) for m in models])

    ordering = params.get("ordering") or default_ordering(stage)
    order = ORDERINGS.get(ordering, ORDERINGS["recent"])
    if ordering == "alpha":
        qs = qs.annotate(title_key=alpha_key(Coalesce("model__name", "custom_name")), extra_key=alpha_key(F("extra")))
    if not stage and text:
        return qs.order_by(F("trashed_at").asc(nulls_first=True), *order)
    return qs.order_by(*order)


def counters() -> dict:
    active = Item.objects.filter(trashed_at__isnull=True)
    late = late_q()
    rows = active.values("stage").annotate(total=Count("id"), late=Count("id", filter=late))
    stages = {s: {"total": 0, "late": 0} for s in STAGE_ORDER}
    for row in rows:
        stages[row["stage"]] = {"total": row["total"], "late": row["late"]}
    return {
        "stages": stages,
        "free": Item.objects.filter(free_q()).count(),
        "late": sum(v["late"] for v in stages.values()),
        "trash": Item.objects.filter(trashed_at__isnull=False).count(),
    }
