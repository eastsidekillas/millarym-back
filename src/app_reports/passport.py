import segno
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from app_production.models import EventKind, FabricSlot, Item, ItemEvent

from .pdf import render_pdf
from .rows import fmt_date, item_fabrics

MAX_ITEMS = 200


def card_url(item: Item) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/production?item={item.pk}"


def qr_svg(url: str) -> str:
    return segno.make(url, error="m").svg_data_uri(border=0, dark="#000")


def meters(value) -> str:
    return f"{value.normalize():f}".replace(".", ",") if value is not None else ""


PASSPORT_SLOTS = [
    (FabricSlot.MAIN, "Ткань основа"),
    (FabricSlot.COMP1, "Ткань компаньон 1"),
    (FabricSlot.COMP2, "Ткань компаньон 2"),
]


def fabric_rows(item: Item) -> list[dict]:
    by_slot = {f.slot: f for f in item.fabrics.all()}
    rows = []
    for slot, label in PASSPORT_SLOTS:
        f = by_slot.get(slot)
        rows.append({"label": label, "name": f.fabric.name if f else "", "meters": meters(f.meters) if f else ""})
    return rows


def passport_context(item: Item) -> dict:
    return {
        "number": item.number,
        "title": item.title,
        "extra": item.extra,
        "for_order": bool(item.reserve),
        "reserve": item.reserve,
        "indiv": item.indiv,
        "indiv_note": item.indiv_note,
        "created": fmt_date(item.created_at),
        "manager": item.manager.short_name if item.manager_id else "",
        "fabrics": fabric_rows(item),
        "fabrics_short": "; ".join(f"{f.get_slot_display()}: {f.fabric.name}" for f in item_fabrics(item)),
        "qr": qr_svg(card_url(item)),
    }


def render_passports(items: list[Item]) -> bytes:
    return render_pdf(
        "reports/passport.html",
        {"passports": [passport_context(item) for item in items], "printed": fmt_date(timezone.now())},
    )


@transaction.atomic
def mark_printed(user, items: list[Item]) -> None:
    now = timezone.now()
    Item.objects.filter(pk__in=[i.pk for i in items]).update(passport_printed_at=now)
    ItemEvent.objects.bulk_create(
        [
            ItemEvent(
                item=item,
                user=user,
                kind=EventKind.PASSPORT,
                text="Паспорт напечатан повторно" if item.passport_printed_at else "Паспорт напечатан",
            )
            for item in items
        ]
    )
    for item in items:
        item.passport_printed_at = now
