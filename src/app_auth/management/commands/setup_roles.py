from django.core.management.base import BaseCommand

from app_auth.roles import sync_roles


class Command(BaseCommand):
    help = "Создать группы и права по таблице app_auth/rights.py (--reset — перезаписать права групп)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Привести права всех групп к таблице")

    def handle(self, *args, reset=False, **options):
        touched = sync_roles(reset=reset)
        self.stdout.write(self.style.SUCCESS(f"Группы: {', '.join(touched) or 'без изменений'}"))
