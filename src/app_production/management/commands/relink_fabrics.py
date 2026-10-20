from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from app_catalog.models import Fabric
from app_production.legacy.fabrics import FabricMatcher
from app_production.models import ItemFabric


class Command(BaseCommand):
    help = (
        "Привязать изделия к тканям справочника вместо скрытых тканей без фото, заведённых переносом "
        "(«manila 01 001» → «Manila 01»). Скрытая ткань без изделий удаляется. Сначала с --dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")

    def handle(self, *args, dry_run, **options):
        orphans = list(Fabric.objects.filter(active=False, photo="").filter(item_fabrics__isnull=False).distinct())
        targets = FabricMatcher(Fabric.objects.filter(Q(active=True) | ~Q(photo="")))
        moved: Counter = Counter()
        left: Counter = Counter()

        with transaction.atomic():
            for orphan in orphans:
                target, _ = targets.find(orphan.name)
                count = ItemFabric.objects.filter(fabric=orphan).count()
                if target is None or target.pk == orphan.pk:
                    left[orphan.name] = count
                    continue
                moved[(orphan.name, target.name)] = count
                if not dry_run:
                    ItemFabric.objects.filter(fabric=orphan).update(fabric=target)
                    orphan.delete()

        head = "ПРОВЕРКА — в базу ничего не записано. " if dry_run else ""
        self.stdout.write(
            f"{head}Скрытых тканей без фото у изделий: {len(orphans)}. "
            f"Привязано к тканям справочника: {len(moved)} ({sum(moved.values())} изд.). Осталось: {len(left)}."
        )
        if moved:
            self.stdout.write("Старое название → ткань в справочнике:")
            for (old, new), n in sorted(moved.items(), key=lambda x: -x[1]):
                self.stdout.write(f"  {n} × {old} → {new}")
        if left:
            self.stdout.write("Не нашлось похожей ткани в справочнике (останутся скрытыми, у изделий сохранятся):")
            for name, n in left.most_common():
                self.stdout.write(f"  {n} × {name}")
