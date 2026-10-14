from datetime import date, timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from app_catalog.models import Deadlines, Fabric, ProductModel, Team


class Stage(models.TextChoices):
    ORDERS = "orders", "Заказы"
    CUT = "cut", "Крой"
    COVER = "cover", "Склад чехлов"
    WORK = "work", "В работе"
    FG = "fg", "СГП"


STAGE_ORDER = [Stage.ORDERS, Stage.CUT, Stage.COVER, Stage.WORK, Stage.FG]


class TrashReason(models.TextChoices):
    SHIPPED = "shipped", "Отгружено"
    DELETED = "deleted", "Удалено"


class FabricSlot(models.TextChoices):
    MAIN = "main", "Основа"
    COMP1 = "comp1", "Компаньон 1"
    COMP2 = "comp2", "Компаньон 2"
    LEATHER = "leather", "Кожзам"


class NumberSequence(models.Model):
    period = models.PositiveSmallIntegerField("год", unique=True)
    last_value = models.PositiveIntegerField("последний номер", default=0)

    class Meta:
        verbose_name = "нумерация"
        verbose_name_plural = "нумерация"

    def __str__(self):
        return f"{self.period}: {self.last_value}"


def format_number(period: int, seq: int) -> str:
    return f"{period % 100:02d}/{seq:04d}"


class Item(models.Model):
    period = models.PositiveSmallIntegerField("год")
    seq = models.PositiveIntegerField("номер в году")
    number = models.CharField("номер", max_length=12, unique=True, editable=False)
    legacy_number = models.CharField("номер в старой системе", max_length=40, blank=True, default="")

    model = models.ForeignKey(ProductModel, models.PROTECT, related_name="items", verbose_name="модель")
    extra = models.CharField("комплектация, дополнения", max_length=500, blank=True, default="")
    comment = models.TextField("комментарий", blank=True, default="")

    reserve = models.CharField("резерв", max_length=300, blank=True, default="")
    reserved_at = models.DateTimeField("резерв с", null=True, blank=True)

    stage = models.CharField("этап", max_length=10, choices=Stage.choices)
    stage_since = models.DateTimeField("на этапе с")
    team = models.ForeignKey(Team, models.PROTECT, null=True, blank=True, related_name="items", verbose_name="бригада")

    fabric_arrived_at = models.DateField("ткань пришла", null=True, blank=True)
    sew_at = models.DateField("выдано в шитьё", null=True, blank=True)
    cover_ready_at = models.DateField("чехол готов", null=True, blank=True)
    work_at = models.DateField("выдано в работу", null=True, blank=True)

    indiv = models.BooleanField("индивидуальный заказ", default=False)
    indiv_note = models.CharField("что особенного", max_length=300, blank=True, default="")
    due_at = models.DateField("срок", null=True, blank=True)

    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, related_name="items", verbose_name="завёл"
    )
    created_at = models.DateTimeField("создано")

    trashed_at = models.DateTimeField("в Корзине с", null=True, blank=True)
    trash_reason = models.CharField("причина", max_length=10, choices=TrashReason.choices, blank=True, default="")

    class Meta:
        verbose_name = "изделие"
        verbose_name_plural = "изделия"
        ordering = ["-stage_since"]
        constraints = [models.UniqueConstraint(fields=["period", "seq"], name="item_period_seq_unique")]
        indexes = [
            models.Index(fields=["stage", "trashed_at"], name="item_stage_trash_idx"),
            models.Index(fields=["stage"], condition=Q(reserve="", trashed_at=None), name="item_free_idx"),
        ]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        self.number = format_number(self.period, self.seq)
        super().save(*args, **kwargs)

    @property
    def in_trash(self) -> bool:
        return self.trashed_at is not None

    @property
    def is_free(self) -> bool:
        return not self.reserve and not self.in_trash and self.stage != Stage.ORDERS

    def warnings(self, today: date | None = None, deadlines: Deadlines | None = None) -> list[str]:
        if not self.indiv or self.in_trash or self.stage == Stage.FG:
            return []
        today = today or timezone.localdate()
        d = deadlines or Deadlines.get()
        days = (today - timezone.localtime(self.created_at).date()).days
        result = []
        if not self.fabric_arrived_at and self.stage == Stage.ORDERS and days > d.fabric_days:
            result.append("fabric")
        if not self.cover_ready_at and self.stage in (Stage.ORDERS, Stage.CUT) and days > d.cut_days:
            result.append("cut")
        if self.due_at and today > self.due_at:
            result.append("output")
        return result


class ItemFabric(models.Model):
    item = models.ForeignKey(Item, models.CASCADE, related_name="fabrics")
    slot = models.CharField("место", max_length=10, choices=FabricSlot.choices)
    fabric = models.ForeignKey(Fabric, models.PROTECT, related_name="item_fabrics", verbose_name="ткань")
    meters = models.DecimalField("метраж", max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "ткань изделия"
        verbose_name_plural = "ткани изделия"
        constraints = [models.UniqueConstraint(fields=["item", "slot"], name="itemfabric_slot_unique")]
        ordering = ["item", "slot"]

    def __str__(self):
        return f"{self.get_slot_display()}: {self.fabric}"


class EventKind(models.TextChoices):
    CREATED = "created", "Создано"
    MOVE = "move", "Перемещение"
    SHIP = "ship", "Отгрузка"
    RETURN_TO_WORK = "return", "Возврат в работу"
    FABRIC = "fabric", "Ткань пришла"
    SEW = "sew", "Выдано в шитьё"
    COVER_READY = "cover_ready", "Чехол готов"
    RESERVE = "reserve", "Резерв"
    EDIT = "edit", "Правка"
    TRASH = "trash", "Удаление в Корзину"
    RESTORE = "restore", "Восстановление"
    COPY = "copy", "Копия"


class ItemEvent(models.Model):
    item = models.ForeignKey(Item, models.PROTECT, related_name="events")
    at = models.DateTimeField("когда", auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, related_name="item_events", verbose_name="кто")
    kind = models.CharField("что", max_length=20, choices=EventKind.choices)
    text = models.CharField("описание", max_length=500)
    data = models.JSONField("данные", default=dict, blank=True)

    class Meta:
        verbose_name = "событие"
        verbose_name_plural = "журнал изменений"
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.item} · {self.text}"


def due_date(created: date, deadlines: Deadlines) -> date:
    return created + timedelta(days=deadlines.output_days)
