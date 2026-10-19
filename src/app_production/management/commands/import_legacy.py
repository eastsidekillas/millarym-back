from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from app_production.legacy.dump import DumpError, read_tables
from app_production.legacy.importer import Importer


class Command(BaseCommand):
    help = (
        "Перенести изделия из старых баз по дампам phpMyAdmin (.sql): живые изделия из «Резервов» "
        "и открытые заказы из «Заказов». Сначала запускайте с --dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--reserv", required=True, help="дамп базы резервов (reserv_db2)")
        parser.add_argument("--orders", required=True, help="дамп базы заказов (zakaz)")
        parser.add_argument("--since", default="2026-01-01", help="заказы с этой даты, ГГГГ-ММ-ДД (по умолчанию 2026-01-01)")
        parser.add_argument(
            "--manager", action="append", default=[], metavar="ИМЯ=ЛОГИН",
            help="сопоставить менеджера из старой базы пользователю, например «Окишева Екатерина=okisheva»",
        )
        parser.add_argument("--report", help="сохранить отчёт ещё и в файл")
        parser.add_argument("--dry-run", action="store_true", help="только отчёт, без записи в базу")

    def handle(self, *args, reserv, orders, since, manager, report, dry_run, **options):
        for path in (reserv, orders):
            if not Path(path).is_file():
                raise CommandError(f"Нет файла {path}.")
        try:
            since_date = date.fromisoformat(since)
        except ValueError:
            raise CommandError("--since: дата в виде ГГГГ-ММ-ДД.") from None
        managers = {}
        for pair in manager:
            name, sep, login = pair.partition("=")
            if not sep or not name.strip() or not login.strip():
                raise CommandError(f"--manager: нужно «Имя=логин», получено «{pair}».")
            managers[name] = login
        try:
            reserv_rows = read_tables(reserv, {"reserv"})["reserv"]
            order_rows = read_tables(orders, {"orders"})["orders"]
        except DumpError as e:
            raise CommandError(f"Не удалось прочитать дамп: {e}") from None
        if not reserv_rows:
            raise CommandError(f"В {reserv} нет таблицы reserv — это точно дамп резервов?")
        if not order_rows:
            raise CommandError(f"В {orders} нет таблицы orders — это точно дамп заказов?")

        importer = Importer(reserv_rows, order_rows, since_date, managers)
        plans = importer.plan()
        if not dry_run:
            importer.apply(plans)
        lines = importer.report.lines(plans, dry_run)
        text = "\n".join(lines)
        self.stdout.write(text)
        if report:
            Path(report).write_text(text + "\n", encoding="utf-8")
