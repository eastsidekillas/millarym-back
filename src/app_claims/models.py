import uuid
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from app_catalog.models import WithPhoto
from app_production.models import Item


class ClaimType(models.TextChoices):
    REVIEW = "review", "На рассмотрении"
    REPAIR = "repair", "Ремонт"
    RETURN = "return", "Возврат"
    RESORT = "resort", "Пересорт"
    SHORTAGE = "shortage", "Недовоз"
    PARTS = "parts", "Замена комплектующих"
    PAID = "paid", "За оплату"
    OTHER = "other", "Другое"


class DefectType(models.TextChoices):
    PRODUCTION = "production", "Производственный"
    DESIGN = "design", "Конструктивный"
    TRANSPORT = "transport", "Транспортировка"
    WAREHOUSE = "warehouse", "Склад"
    MATERIAL = "material", "Дефект материала"
    PARTS = "parts", "Замена комплектующих"
    MISUSE = "misuse", "Нарушение правил эксплуатации"
    REJECTED = "rejected", "Претензия не принята"
    OTHER = "other", "Другое"


class ClaimState(models.TextChoices):
    OPEN = "open", "Открыта"
    DONE = "done", "Выполнена"
    WITHDRAWN = "withdrawn", "Снята покупателем"


CLOSED_STATES = (ClaimState.DONE, ClaimState.WITHDRAWN)


class Sender(models.TextChoices):
    YULDASHEVA = "yuldasheva", "ИП Юлдашева О.А."
    OKULOVA = "okulova", "ИП Окулова В.А."
    FACTORY = "factory", "Фабрика мебели"


class ClaimSequence(models.Model):
    period = models.PositiveSmallIntegerField("год", unique=True)
    last_value = models.PositiveIntegerField("последний номер", default=0)

    class Meta:
        verbose_name = "нумерация рекламаций"
        verbose_name_plural = "нумерация рекламаций"

    @classmethod
    @transaction.atomic
    def next(cls, period: int) -> int:
        seq, _ = cls.objects.select_for_update().get_or_create(period=period)
        seq.last_value += 1
        seq.save(update_fields=["last_value"])
        return seq.last_value


class Claim(models.Model):
    period = models.PositiveSmallIntegerField("год", editable=False)
    seq = models.PositiveIntegerField("номер в году", editable=False)
    number = models.CharField("номер акта", max_length=12, unique=True, editable=False)

    act_date = models.DateField("дата в акте клиента", null=True, blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="claims", verbose_name="менеджер"
    )
    counterparty = models.CharField("контрагент", max_length=300, blank=True, default="")

    item = models.ForeignKey(
        Item, models.SET_NULL, null=True, blank=True, related_name="claims", verbose_name="изделие в базе"
    )
    product = models.CharField("изделие", max_length=300, blank=True, default="")
    item_number = models.CharField("номер изделия", max_length=40, blank=True, default="")
    color = models.CharField("цвет, ткани", max_length=300, blank=True, default="")
    part = models.TextField("деталь", blank=True, default="")
    description = models.TextField("описание претензии", blank=True, default="")
    package_data = models.TextField("данные с упаковки", blank=True, default="")
    waybill = models.CharField("№ ТН и дата отгрузки", max_length=200, blank=True, default="")
    sender = models.CharField("отправитель", max_length=20, choices=Sender.choices, blank=True, default="")
    invoice_price = models.DecimalField("цена по накладной", max_digits=10, decimal_places=2, null=True, blank=True)
    customer_shipped_at = models.DateField("дата отгрузки конечному покупателю", null=True, blank=True)
    demands = models.TextField("требования покупателя", blank=True, default="")

    claim_type = models.CharField("тип претензии", max_length=20, choices=ClaimType.choices, default=ClaimType.REVIEW)
    arrived_at = models.DateField("дата поступления на склад", null=True, blank=True)
    kit = models.TextField("комплектация", blank=True, default="")
    sent_back_at = models.DateField("дата отправки покупателю", null=True, blank=True)

    appearance = models.TextField("внешний вид поступившего изделия", blank=True, default="")
    research = models.TextField("результаты исследований", blank=True, default="")
    defect_type = models.CharField("вид дефекта", max_length=20, choices=DefectType.choices, blank=True, default="")
    remedy = models.TextField("меры по устранению", blank=True, default="")

    state = models.CharField("состояние", max_length=10, choices=ClaimState.choices, default=ClaimState.OPEN)
    closed_at = models.DateTimeField("закрыта", null=True, blank=True, editable=False)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="+", verbose_name="закрыл", editable=False
    )
    close_note = models.TextField("чем закончилась", blank=True, default="")

    video_links = models.JSONField("ссылки на видео", default=list, blank=True)

    restore_cost = models.DecimalField("расходы по восстановлению", max_digits=10, decimal_places=2, null=True, blank=True)
    finance_note = models.TextField("финансовая часть: пояснение", blank=True, default="")

    created_at = models.DateTimeField("заведена", default=timezone.now, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, related_name="+", verbose_name="завёл", editable=False
    )
    updated_at = models.DateTimeField("изменена", auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, related_name="+", verbose_name="изменил", editable=False
    )

    class Meta:
        verbose_name = "рекламация"
        verbose_name_plural = "рекламации"
        ordering = ["-period", "-seq"]
        constraints = [models.UniqueConstraint(fields=["period", "seq"], name="claim_period_seq_unique")]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.seq:
            self.period = timezone.localdate().year
            self.seq = ClaimSequence.next(self.period)
        self.number = f"{self.period % 100:02d}/{self.seq:03d}"
        super().save(*args, **kwargs)


def claim_file_path(instance, filename):
    return f"claims/files/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class ClaimFile(models.Model):
    """Документы по рекламации: официальный ответ на претензию и т. п."""

    claim = models.ForeignKey(Claim, models.CASCADE, related_name="files", verbose_name="рекламация")
    file = models.FileField("файл", upload_to=claim_file_path)
    name = models.CharField("имя файла", max_length=255)
    size = models.PositiveIntegerField("размер, байт", default=0)
    created_at = models.DateTimeField("добавлен", auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, related_name="+", verbose_name="добавил")

    class Meta:
        verbose_name = "файл рекламации"
        verbose_name_plural = "файлы рекламаций"
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.name


class ClaimPhoto(WithPhoto):
    photo_dir = "claims"

    claim = models.ForeignKey(Claim, models.CASCADE, related_name="photos", verbose_name="рекламация")
    created_at = models.DateTimeField("добавлено", auto_now_add=True)

    class Meta:
        verbose_name = "фото рекламации"
        verbose_name_plural = "фото рекламаций"
        ordering = ["created_at", "id"]
