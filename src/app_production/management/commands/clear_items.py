from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app_production.models import Item, ItemEvent, NumberSequence


class Command(BaseCommand):
    help = (
        "Удалить ВСЕ изделия навсегда (с историей и тканями изделий) и начать нумерацию заново — для тестового "
        "сервера. Справочники и пользователи остаются. --claims — заодно удалить рекламации. Без --yes только отчёт."
    )

    def add_arguments(self, parser):
        parser.add_argument("--claims", action="store_true", help="удалить и рекламации (с фото и файлами)")
        parser.add_argument("--yes", action="store_true", help="подтверждаю: удалить без возможности вернуть")

    def handle(self, *args, claims, yes, **options):
        from app_claims.models import Claim, ClaimFile, ClaimPhoto, ClaimSequence

        items = Item.all_objects.count()
        events = ItemEvent.objects.count()
        claims_count = Claim.objects.count() if claims else 0
        summary = f"Изделий: {items}, записей истории: {events}" + (f", рекламаций: {claims_count}" if claims else "")
        if not yes:
            self.stdout.write(f"ПРОВЕРКА — ничего не удалено. Будет удалено навсегда: {summary}.")
            self.stdout.write("Чтобы удалить, запустите ещё раз с --yes. Сначала сделайте копию базы.")
            return
        if not items and not claims_count:
            raise CommandError("Удалять нечего.")

        files = []
        with transaction.atomic():
            if claims:
                for photo in ClaimPhoto.objects.all():
                    files += [f for f in (photo.photo, photo.photo_thumb) if f]
                files += [d.file for d in ClaimFile.objects.all() if d.file]
                Claim.objects.all().delete()
                ClaimSequence.objects.all().delete()
            ItemEvent.objects.all().delete()
            Item.all_objects.all().delete()
            NumberSequence.objects.all().delete()
        for f in files:
            f.storage.delete(f.name)
        self.stdout.write(f"Удалено: {summary}. Новые изделия начнутся с номера 1 текущего года.")
