import time
from datetime import datetime, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone


def next_run(now: datetime, at: str) -> datetime:
    hour, minute = (int(x) for x in at.split(":"))
    run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


class Command(BaseCommand):
    help = "Фоновые задачи: каждый день в указанное время (по времени фабрики) чистит Корзину."

    def add_arguments(self, parser):
        parser.add_argument("--at", default="03:00", help="время запуска, ЧЧ:ММ (по умолчанию 03:00)")
        parser.add_argument("--now", action="store_true", help="сначала выполнить задачи сразу")

    def handle(self, *args, at="03:00", now=False, **options):
        if now:
            self.run_jobs()
        while True:
            wait = (next_run(timezone.localtime(), at) - timezone.localtime()).total_seconds()
            self.stdout.write(f"Следующий запуск через {wait / 3600:.1f} ч.", ending="\n")
            self.stdout.flush()
            time.sleep(max(wait, 1))
            self.run_jobs()

    def run_jobs(self):
        close_old_connections()
        self.stdout.write(timezone.localtime().strftime("%d.%m.%y %H:%M"))
        try:
            call_command("purge_trash", stdout=self.stdout)
        except Exception as err:  # noqa: BLE001 — одна неудача не должна останавливать расписание
            self.stderr.write(f"purge_trash: {err}")
        self.stdout.flush()
