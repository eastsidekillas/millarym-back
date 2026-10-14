from django.core.management import call_command

from app_auth.models import User
from app_catalog.models import Category, Fabric, ProductModel, Team


class Fixtures:
    @classmethod
    def make_fixtures(cls):
        call_command("create_users", stdout=open("/dev/null", "w"))
        cls.users = {u.username: u for u in User.objects.all()}
        cls.director = cls.users["yuldasheva"]
        cls.cutter = cls.users["kotomtseva"]
        cls.manager = cls.users["okisheva"]
        cls.master = cls.users["plokhikh"]
        cls.storekeeper = cls.users["voznesenskaya"]
        sofas = Category.objects.get(name="Прямые диваны")
        cls.model = ProductModel.objects.create(name="Бостон", category=sofas)
        cls.other_model = ProductModel.objects.create(name="Флоренция", category=sofas)
        cls.velour = Fabric.objects.create(name="Велюр 03")
        cls.leather = Fabric.objects.create(name="Экокожа белая")
        cls.team = Team.objects.create(name="Бригада Иванова", foreman="Иванов")

    def fabrics(self, **extra):
        result = [{"slot": "main", "fabric": self.velour, "meters": 12}]
        for slot, fabric in extra.items():
            result.append({"slot": slot, "fabric": fabric, "meters": None})
        return result
