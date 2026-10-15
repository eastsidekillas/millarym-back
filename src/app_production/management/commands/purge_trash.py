from django.core.management.base import BaseCommand

from app_catalog.models import Deadlines
from app_production.models import Item
from app_production.services import purge_trash


class Command(BaseCommand):
    help = "Окончательно удаляет из Корзины изделия, у которых вышел срок хранения. История остаётся."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="только показать, что удалится")

    def handle(self, *args, dry_run=False, **options):
        days = Deadlines.get().trash_days
        if dry_run:
            numbers = list(Item.objects.due_for_purge().order_by("period", "seq").values_list("number", flat=True))
            verb = "Удалится"
        else:
            numbers = purge_trash()
            verb = "Удалено"
        self.stdout.write(f"{verb} из Корзины (лежали больше {days} дн.): {len(numbers)}")
        if numbers:
            self.stdout.write(", ".join(numbers))
