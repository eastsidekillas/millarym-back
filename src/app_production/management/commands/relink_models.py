from collections import Counter

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from app_catalog.models import ProductModel
from app_production.legacy import text as t
from app_production.legacy.importer import LEGACY_USER
from app_production.models import EventKind, Item, ItemEvent


class Command(BaseCommand):
    help = (
        "Перенесённым изделиям «вне справочника» подставить модель из справочника, если её добавили после "
        "переноса («Дуглас 1400 диван Накладки венге» → «Дуглас 1400», комплектация «Накладки венге»). Сначала с --dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")

    def handle(self, *args, dry_run, **options):
        matcher = t.ModelMatcher(ProductModel.objects.all())
        items = list(Item.all_objects.filter(model__isnull=True).exclude(legacy_number="").exclude(custom_name=""))
        user = get_user_model().objects.filter(username=LEGACY_USER).first()
        found: Counter = Counter()
        left: Counter = Counter()

        with transaction.atomic():
            for item in items:
                model, rest = matcher.match(item.custom_name)
                if model is None:
                    left[item.custom_name] += 1
                    continue
                found[(item.custom_name, model.name)] += 1
                if dry_run:
                    continue
                old = item.custom_name
                item.model, item.custom_name = model, ""
                if not item.extra:
                    item.extra = t.extra_from(rest)[:500]
                item.save(update_fields=["model", "custom_name", "extra"])
                if user:
                    ItemEvent.objects.create(
                        item=item, user=user, kind=EventKind.EDIT,
                        text=f"Название: {old} (вне справочника) → {model.name}", data={"legacy": True},
                    )

        head = "ПРОВЕРКА — в базу ничего не записано. " if dry_run else ""
        self.stdout.write(
            f"{head}Перенесённых изделий вне справочника: {len(items)}. "
            f"Нашлась модель: {sum(found.values())}. Осталось вне справочника: {sum(left.values())}."
        )
        if found:
            self.stdout.write("Старое название → модель справочника:")
            for (old, new), n in found.most_common():
                self.stdout.write(f"  {n} × {old} → {new}")
        if left:
            self.stdout.write("Модели нет в справочнике:")
            for name, n in left.most_common():
                self.stdout.write(f"  {n} × {name}")
