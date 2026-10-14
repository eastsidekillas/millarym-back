import random
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from app_auth.models import User
from app_auth.rights import USERS
from app_catalog.models import Category, Fabric, ProductModel, Team
from app_production import services as s
from app_production.models import Item

MODELS = [
    ("Бостон БД", "Прямые диваны"),
    ("Флоренция БД", "Прямые диваны"),
    ("Лангепас диван", "Прямые диваны"),
    ("Рио диван", "Малогабаритные диваны"),
    ("Куба 1200 диван", "Малогабаритные диваны"),
    ("Монтана Престиж", "Угловые диваны"),
    ("Мюнхен ДУ", "Угловые диваны"),
    ("Лондон ДУ", "Угловые диваны"),
    ("Сочи ДУ", "Угловые диваны"),
    ("Дубай кресло", "Кресла"),
    ("Куба кресло", "Кресла"),
    ("Кровать Лион 160", "Кровати"),
    ("Кровать Ницца 140", "Кровати"),
    ("Пуф Рио", "Пуфы"),
]
FABRICS = [
    "kioto beige", "kioto grafit 4k", "monako 5 4k", "ultra cashmere", "easton 02 4k", "ankona 9 4k",
    "savana grey 4f", "marvel grey kz", "vital java 4e", "debut 38 4k", "favorit indigo 4k", "teos milk 4k",
]
LEATHER = ["экокожа белая", "экокожа венге", "экокожа графит"]
TEAMS = [("Попов В.", "Попов В."), ("Хамитов Р.", "Хамитов Р."), ("Панасова О.", "Панасова О."), ("Дектеренко Е.", "Дектеренко Е.")]
RESERVES = [
    "согл.", "частное лицо", "Мир мебели (Филина)", "ИП Фоминых", "ИП Бочкарева Е.М.", "ООО Статус",
    "ООО Орион (торговый зал)", "Фобос (Новоуральск) Жданова", "Конев (Постникова)", "Миларум Лесной",
]
EXTRAS = ["", "", "левый угол", "правый угол", "накладки венге", "левый угол, накладки белые", "правый угол, накладки серые"]
INDIV_NOTES = ["нестандартный размер 2400×1000", "своя ткань заказчика", "удлинённое спальное место", "другая высота опор"]


class Clock:
    def __init__(self, start: datetime, limit: datetime):
        self.now = start
        self.limit = limit

    def step(self, days: float) -> None:
        candidate = self.now + timedelta(days=days, minutes=random.randint(5, 240))
        ceiling = self.limit - timedelta(minutes=random.randint(5, 60))
        self.now = max(min(candidate, ceiling), self.now + timedelta(minutes=1))

    @contextmanager
    def frozen(self):
        with mock.patch("django.utils.timezone.now", lambda: self.now):
            yield


class Command(BaseCommand):
    help = "Тестовые данные для разработки: сотрудники, справочники и ~60 изделий с историей. Не для сервера."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="milarum2026", help="пароль для 7 сотрудников (только новых)")
        parser.add_argument("--items", type=int, default=60)
        parser.add_argument("--append", action="store_true", help="добавить, даже если изделия уже есть")
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, password, items, append, seed, **options):
        if not settings.DEBUG:
            raise CommandError("Только для разработки (DEBUG=True).")
        if Item.objects.exists() and not append:
            raise CommandError("Изделия уже есть. Чтобы добавить ещё, запустите с --append.")
        random.seed(seed)
        with transaction.atomic():
            users = self.users(password)
            models, fabrics, leather, teams = self.catalog()
            created = [self.item(users, models, fabrics, leather, teams) for _ in range(items)]
        stages = {}
        for item in Item.objects.filter(pk__in=[i.pk for i in created]):
            key = "trash" if item.trashed_at else item.stage
            stages[key] = stages.get(key, 0) + 1
        self.stdout.write(self.style.SUCCESS(f"Изделий: {len(created)} {stages}"))
        self.stdout.write(f"Вход: логины {', '.join(u[0] for u in USERS)}; пароль новых — {password}")

    def users(self, password: str) -> dict[str, User]:
        result = {}
        for username, last, first, group in USERS:
            user, new = User.objects.get_or_create(username=username, defaults={"last_name": last, "first_name": first})
            if new:
                user.set_password(password)
                user.save()
                user.groups.add(Group.objects.get(name=group))
            result[username] = user
        return result

    def catalog(self):
        cats = {c.name: c for c in Category.objects.all()}
        models = [
            ProductModel.objects.get_or_create(name=name, defaults={"category": cats[cat]})[0] for name, cat in MODELS
        ]
        fabrics = [Fabric.objects.get_or_create(name=name)[0] for name in FABRICS]
        leather = [Fabric.objects.get_or_create(name=name)[0] for name in LEATHER]
        teams = [Team.objects.get_or_create(name=name, defaults={"foreman": f})[0] for name, f in TEAMS]
        return models, fabrics, leather, teams

    def item(self, u, models, fabrics, leather, teams) -> Item:
        managers = [u["okisheva"], u["postnikova"]]
        cutter, master, store, boss = u["kotomtseva"], u["plokhikh"], u["voznesenskaya"], u["yuldasheva"]
        real_now = timezone.now()
        today = timezone.localdate()
        start_day = today - timedelta(days=random.randint(1, 45))
        start = timezone.make_aware(datetime.combine(start_day, time(random.randint(8, 16), random.randint(0, 59))))
        clock = Clock(start, real_now)

        reserve = random.choice(RESERVES) if random.random() < 0.6 else ""
        fab = [{"slot": "main", "fabric": random.choice(fabrics), "meters": random.choice([8, 9.5, 10, 12, 12.5, 14])}]
        if random.random() < 0.5:
            fab.append({"slot": "comp1", "fabric": random.choice(fabrics), "meters": random.choice([2, 3, 4.5])})
        if random.random() < 0.15:
            fab.append({"slot": "comp2", "fabric": random.choice(fabrics), "meters": 2})
        if random.random() < 0.3:
            fab.append({"slot": "leather", "fabric": random.choice(leather), "meters": random.choice([1.5, 2, 3])})
        indiv = bool(reserve) and random.random() < 0.35

        custom = random.random() < 0.04
        with clock.frozen():
            [item] = s.create_items(
                random.choice(managers),
                model=None if custom else random.choice(models),
                custom_name="Угловой диван по эскизу заказчика" if custom else "",
                fabrics=fab,
                extra=random.choice(EXTRAS),
                reserve=reserve,
                indiv=indiv,
                indiv_note=random.choice(INDIV_NOTES) if indiv and random.random() < 0.7 else "",
                comment="срочно" if random.random() < 0.08 else "",
            )
            age = (today - start_day).days
            target = random.choices(["orders", "cut", "cover", "work", "fg", "shipped"], [5, 3, 2, 3, 3, 1])[0] if reserve else random.choices(["cut", "cover", "work", "fg", "shipped"], [3, 2, 3, 4, 1])[0]
            plan = ["orders", "cut", "cover", "work", "fg", "shipped"]
            ops = 2 + 3 * (plan.index(target) - plan.index(item.stage))
            gap = max(age / ops, 0.05)

            def later():
                clock.step(random.uniform(gap * 0.4, gap))

            if item.stage == "orders":
                if target != "orders" or random.random() < 0.4:
                    later()
                    item = s.mark_fabric_arrived(cutter, item.pk)
                if target != "orders":
                    later()
                    item = s.move(cutter, item.pk, "cut")
            if target == "cut":
                if random.random() < 0.6:
                    later()
                    item = s.mark_sew(cutter, item.pk)
                    if random.random() < 0.5:
                        later()
                        item = s.mark_cover_ready(cutter, item.pk)
            if plan.index(target) >= plan.index("cover"):
                later()
                item = s.mark_sew(cutter, item.pk)
                later()
                item = s.mark_cover_ready(cutter, item.pk)
                later()
                item = s.move(cutter, item.pk, "cover")
            if plan.index(target) >= plan.index("work"):
                later()
                item = s.move(master, item.pk, "work", team=random.choice(teams))
            if plan.index(target) >= plan.index("fg"):
                later()
                item = s.move(master, item.pk, "fg")
            if target == "shipped":
                later()
                item = s.ship(store, item.pk)
            if item.stage == "orders" and random.random() < 0.1:
                later()
                item = s.set_reserve(random.choice(managers), item.pk, random.choice(RESERVES))
            if target in ("cut", "cover") and not item.reserve and random.random() < 0.15:
                later()
                item = s.set_reserve(random.choice(managers), item.pk, random.choice(RESERVES))
            if target == "cut" and random.random() < 0.05:
                later()
                item = s.trash(boss, item.pk)
        return item
