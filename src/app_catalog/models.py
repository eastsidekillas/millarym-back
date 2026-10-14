from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from .images import new_name, shrink


def photo_path(instance, filename):
    return f"{instance.photo_dir}/{filename}"


def thumb_path(instance, filename):
    return f"{instance.photo_dir}/thumbs/{filename}"


class WithPhoto(models.Model):
    photo_dir = "photos"

    photo = models.ImageField("фото", upload_to=photo_path, blank=True)
    photo_thumb = models.ImageField("превью", upload_to=thumb_path, blank=True, editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).values_list("photo", "photo_thumb").first() if self.pk else None
        if self.photo and not self.photo._committed:
            full, thumb = shrink(self.photo)
            name = new_name()
            self.photo.save(name, full, save=False)
            self.photo_thumb.save(name, thumb, save=False)
        elif not self.photo:
            self.photo_thumb = ""
        super().save(*args, **kwargs)
        if old:
            storage = self.photo.storage
            for path, current in zip(old, (self.photo.name, self.photo_thumb.name)):
                if path and path != current:
                    storage.delete(path)


class Category(models.Model):
    name = models.CharField("название", max_length=120, unique=True)
    sort = models.PositiveSmallIntegerField("порядок", default=0)
    active = models.BooleanField("активна", default=True)

    class Meta:
        ordering = ["sort", "name"]
        verbose_name = "категория"
        verbose_name_plural = "категории"

    def __str__(self):
        return self.name


class ProductModel(WithPhoto):
    photo_dir = "models"

    name = models.CharField("название", max_length=150)
    category = models.ForeignKey(Category, models.PROTECT, related_name="models", verbose_name="категория")
    active = models.BooleanField("активна", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "модель"
        verbose_name_plural = "модели"
        constraints = [models.UniqueConstraint(Lower("name"), name="productmodel_name_unique_ci")]

    def __str__(self):
        return self.name


class Fabric(WithPhoto):
    photo_dir = "fabrics"

    name = models.CharField("название", max_length=150)
    active = models.BooleanField("активна", default=True)
    created_at = models.DateTimeField("добавлена", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "ткань"
        verbose_name_plural = "ткани"
        constraints = [models.UniqueConstraint(Lower("name"), name="fabric_name_unique_ci")]

    def __str__(self):
        return self.name


class KitOption(models.Model):
    name = models.CharField("название", max_length=120, unique=True)
    sort = models.PositiveSmallIntegerField("порядок", default=0)
    active = models.BooleanField("активна", default=True)

    class Meta:
        ordering = ["sort", "name"]
        verbose_name = "комплектация"
        verbose_name_plural = "комплектация"

    def __str__(self):
        return self.name


class Team(models.Model):
    name = models.CharField("бригада", max_length=120, unique=True)
    foreman = models.CharField("бригадир", max_length=120, blank=True, default="")
    sort = models.PositiveSmallIntegerField("порядок", default=0)
    active = models.BooleanField("активна", default=True)

    class Meta:
        ordering = ["sort", "name"]
        verbose_name = "бригада"
        verbose_name_plural = "бригады"

    def __str__(self):
        return self.name


class Deadlines(models.Model):
    fabric_days = models.PositiveSmallIntegerField("ждём ткань, дней", default=10)
    cut_days = models.PositiveSmallIntegerField("крой, дней", default=20)
    output_days = models.PositiveSmallIntegerField("выпуск, дней", default=30)
    trash_days = models.PositiveSmallIntegerField("хранить в Корзине, дней", default=30)

    class Meta:
        verbose_name = "сроки"
        verbose_name_plural = "сроки"

    def __str__(self):
        return "Сроки"

    def clean(self):
        if self.pk not in (None, 1):
            raise ValidationError("Настройки сроков одни на всю CRM.")

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "Deadlines":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
