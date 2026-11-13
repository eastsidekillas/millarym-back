import re
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from app_production.models import STAGE_ORDER, AmountUnit, FabricSlot, Item, Stage, TrashReason

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


def amount(f) -> str:
    """«12,5 м» или «2 шт» — у компаньонов бывает в штуках."""
    return f"{f.meters.normalize():f}".replace(".", ",") + (" шт" if f.unit == AmountUnit.PIECES else " м")


def fabrics_text(item: Item, meters: bool = False) -> str:
    parts = []
    for f in item_fabrics(item):
        text = f"{f.get_slot_display()}: {f.fabric.name}"
        if meters and f.meters is not None:
            text += " " + amount(f)
        parts.append(text)
    return "\n".join(parts)


def meters_text(item: Item) -> str:
    """Метраж отдельной колонкой, строка в строку с «Ткани»: в названии ткани тоже бывают цифры («Vichy 03 14 м»)."""
    lines = [amount(f) if f.meters is not None else "—" for f in item_fabrics(item)]
    return "\n".join(lines) if any(line != "—" for line in lines) else ""


def where(item: Item) -> str:
    if item.purged_at:
        verb = "Отгружено" if item.trash_reason == TrashReason.SHIPPED else "Удалено"
        return f"{verb} {fmt_date(item.trashed_at)}"
    if item.trashed_at:
        verb = "отгружено" if item.trash_reason == TrashReason.SHIPPED else "удалено"
        return f"Корзина: {verb} {fmt_date(item.trashed_at)}"
    return item.get_stage_display()


def sewing(item: Item) -> str:
    """Отдельная колонка для швейного цеха: что из выданного шьют и что уже отшито. Только на крое."""
    if item.trashed_at or item.stage != Stage.CUT:
        return ""
    if item.cover_ready_at:
        return f"отшит {fmt_date(item.cover_ready_at)}"
    if item.sew_at:
        return f"в шитье {fmt_date(item.sew_at)}"
    return ""


CORNER = re.compile(r"^(лев|прав)\w*(\s+угол)?$", re.IGNORECASE)
OVERLAYS = re.compile(r"^накладки\s+(.+)$", re.IGNORECASE)
LEGACY_SEP = " · "


def split_extra(extra: str) -> tuple[str, str, str]:
    """«правый угол, накладки венге, без ножек» → («Правый», «венге», «без ножек»): колонки номенклатурного плана."""
    corner, overlays, rest = "", "", []
    for part in (p.strip() for p in (extra or "").split(",")):
        if not part:
            continue
        if not corner and (m := CORNER.match(part)):
            corner = "Левый" if m.group(1).lower() == "лев" else "Правый"
        elif not overlays and (m := OVERLAYS.match(part)):
            overlays = m.group(1).strip().lower()
        else:
            rest.append(part)
    return corner, overlays, ", ".join(rest)


def order_numbers(legacy_number: str) -> str:
    """Номера заказов из старого номера: «114542 · 9578/ЗАК · 9580/ЗАК» → «9578, 9580»."""
    parts = (p.strip() for p in (legacy_number or "").split(LEGACY_SEP))
    return ", ".join(p.removesuffix("/ЗАК") for p in parts if p.endswith("/ЗАК"))


def manager_name(item: Item) -> str:
    user = item.manager
    return user.last_name.strip() or user.username


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
    group_photo: Photo | None = None

    def as_json(self) -> dict:
        return {
            "item_id": self.item_id,
            "number": self.number,
            "cells": self.cells,
            "photos": [{"name": p.name, "url": p.url} for p in self.photos],
            "mark": self.mark,
            "group_photo": {"name": self.group_photo.name, "url": self.group_photo.url} if self.group_photo else None,
            "group": self.group,
        }


def photos(item: Item) -> list[Photo]:
    result = []
    for f in item_fabrics(item):
        thumb = f.fabric.photo_thumb
        result.append(Photo(f.fabric.name, thumb.path if thumb else None, thumb.url if thumb else None))
    return result


def model_photo(item: Item) -> Photo | None:
    """Фото модели — одно на группу в отчёте, а не у каждого изделия."""
    model = item.model
    if not model or not model.photo_thumb:
        return None
    return Photo(model.name, model.photo_thumb.path, model.photo_thumb.url)
