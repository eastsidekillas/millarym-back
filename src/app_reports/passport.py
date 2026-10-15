from pathlib import Path

import segno
from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from app_production.errors import ActionError
from app_production.models import EventKind, Item, ItemEvent

from .rows import fmt_date, item_fabrics

ASSETS = Path(__file__).resolve().parent / "assets"
MAX_ITEMS = 200


def card_url(item: Item) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/production?item={item.pk}"


def qr_svg(url: str) -> str:
    return segno.make(url, error="m").svg_data_uri(border=0, dark="#000")


def meters(value) -> str:
    return f"{value.normalize():f}".replace(".", ",") + " м" if value is not None else ""


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
        "fabrics": [
            {"slot": f.get_slot_display(), "name": f.fabric.name, "meters": meters(f.meters)} for f in item_fabrics(item)
        ],
        "qr": qr_svg(card_url(item)),
    }


def render_passports(items: list[Item]) -> bytes:
    html = render_to_string(
        "reports/passport.html",
        {
            "passports": [passport_context(item) for item in items],
            "printed": fmt_date(timezone.now()),
            "fonts": (ASSETS / "fonts").as_uri(),
            "logo": (ASSETS / "logo.png").as_uri(),
        },
    )
    try:
        from weasyprint import HTML
    except OSError:
        raise ActionError("Паспорт не собрать: на сервере не найдена библиотека Pango (см. README, «Паспорт изделия»).")
    return HTML(string=html, base_url=str(ASSETS)).write_pdf()


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
