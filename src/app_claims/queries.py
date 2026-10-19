from datetime import datetime, time

from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import CLOSED_STATES, Claim, ClaimState, ClaimType, DefectType


def filter_claims(qs: QuerySet[Claim], params, skip: str = "") -> QuerySet[Claim]:
    text = (params.get("q") or "").strip()
    if text:
        qs = qs.filter(
            Q(number__icontains=text)
            | Q(counterparty__icontains=text)
            | Q(product__icontains=text)
            | Q(item_number__icontains=text)
            | Q(description__icontains=text)
        )
    state = params.get("state")
    if state == "closed" and skip != "state":
        qs = qs.filter(state__in=CLOSED_STATES)
    elif state and skip != "state":
        qs = qs.filter(state=state)
    for key in ("claim_type", "defect_type", "sender"):
        value = params.get(key)
        if value and key != skip:
            qs = qs.filter(**{key: value})
    start, end = parse_date(params.get("from") or ""), parse_date(params.get("to") or "")
    if start:
        qs = qs.filter(created_at__gte=timezone.make_aware(datetime.combine(start, time.min)))
    if end:
        qs = qs.filter(created_at__lte=timezone.make_aware(datetime.combine(end, time.max)))
    return qs


def stats(params) -> dict:
    base = Claim.objects.all()

    def counts(field, enum):
        rows = dict(filter_claims(base, params, skip=field).values_list(field).annotate(n=Count("id")))
        items = [{"id": value, "name": label, "count": rows.get(value, 0)} for value, label in enum.choices]
        if field == "defect_type" and rows.get(""):
            items.append({"id": "none", "name": "Не указан", "count": rows[""]})
        return items

    return {
        "total": filter_claims(base, params).count(),
        "defect_type": counts("defect_type", DefectType),
        "claim_type": counts("claim_type", ClaimType),
        "state": counts("state", ClaimState),
    }
