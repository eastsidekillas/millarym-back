from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from app_production.models import STAGE_ORDER, FabricSlot, Item, TrashReason

SLOT_ORDER = list(FabricSlot.values)


def ru_key(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def fmt_date(value) -> str:
    if not value:
        return ""
    if not isinstance(value, date) or hasattr(value, "hour"):
        value = timezone.localtime(value).date()
    return value.strftime("%d.%m.%y")


def item_title(item: Item) -> str:
    return f"{item.title}, {item.extra}" if item.extra else item.title


def item_fabrics(item: Item) -> list:
    return sorted(item.fabrics.all(), key=lambda f: SLOT_ORDER.index(f.slot))


def fabrics_text(item: Item, meters: bool = False) -> str:
    parts = []
    for f in item_fabrics(item):
        text = f"{f.get_slot_display()}: {f.fabric.name}"
        if meters and f.meters is not None:
            text += f" {f.meters.normalize():f} м".replace(".", ",")
        parts.append(text)
    return "\n".join(parts)


def where(item: Item) -> str:
    if item.purged_at:
        verb = "Отгружено" if item.trash_reason == TrashReason.SHIPPED else "Удалено"
        return f"{verb} {fmt_date(item.trashed_at)}"
    if item.trashed_at:
        verb = "отгружено" if item.trash_reason == TrashReason.SHIPPED else "удалено"
        return f"Корзина: {verb} {fmt_date(item.trashed_at)}"
    return item.get_stage_display()


def stage_index(item: Item) -> int:
    return len(STAGE_ORDER) if item.trashed_at else STAGE_ORDER.index(item.stage)


@dataclass
class Photo:
    name: str
    path: str | None
    url: str | None


@dataclass
class Row:
    item_id: int
    number: str
    cells: dict
    photos: list[Photo] = field(default_factory=list)
    mark: str = ""
    group: str = ""

    def as_json(self) -> dict:
        return {
            "item_id": self.item_id,
            "number": self.number,
            "cells": self.cells,
            "photos": [{"name": p.name, "url": p.url} for p in self.photos],
            "mark": self.mark,
            "group": self.group,
        }


def photos(item: Item) -> list[Photo]:
    result = []
    for f in item_fabrics(item):
        thumb = f.fabric.photo_thumb
        result.append(Photo(f.fabric.name, thumb.path if thumb else None, thumb.url if thumb else None))
    return result
