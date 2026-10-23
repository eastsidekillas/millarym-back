import tempfile
from datetime import date
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from app_catalog.models import Category, Fabric, ProductModel, Team
from app_production import services as s
from app_production.legacy import text as t
from app_production.legacy.dump import DumpError, read_tables
from app_production.models import EventKind, Item, Stage

from .base import Fixtures


def unix(d: date) -> int:
    return int(timezone.make_aware(timezone.datetime(d.year, d.month, d.day, 0, 0)).timestamp())


RESERV_COLS = "id, photo, product_name, comment, price, main_tex, sec_tex, third_tex, skin, reserv, reserv_date, status, work_date, work_datetime, store_date"
ORDER_COLS = (
    "order_id, add_date, end_date, goods_name, price, goods_ip, goods_man, goods_main_tex, goods_sec_tex, "
    "goods_third_tex, goods_skin, goods_main_tex_m, goods_sec_tex_m, goods_third_tex_m, goods_skin_m, "
    "goods_get_date, add_comment, tex_date, cut_date, advanced, tex_none, shipped"
)


def q(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def insert(table: str, cols: str, rows: list[tuple]) -> str:
    cols_sql = ", ".join(f"`{c.strip()}`" for c in cols.split(","))
    values = ",\n".join("(" + ", ".join(q(v) for v in row) + ")" for row in rows)
    return f"INSERT INTO `{table}` ({cols_sql}) VALUES\n{values};\n"


def reserv_row(id_, name, status, main="Велюр_03.jpg", reserve="", comment="", sec="", skin="", team="", work="", store="", reserv_date=""):
    return (id_, "", name, comment, 0, main, sec, "", skin, reserve, reserv_date, status, team, work, store)


def order_row(id_, name, added, ip="ИП Петров", man="Окишева Екатерина", main="velour_03.jpg", main_m=12.5, tex=None, cut=None, shipped="", comment="", tex_none=""):
    return (
        id_, unix(added), unix(added) + 30 * 86400, "&nbsp;" + name, "", ip, man, main, ".\xa0", ".\xa0", ".\xa0",
        main_m, None, 0, None, unix(added), comment, unix(tex) if tex else 0, unix(cut) if cut else 0, "", tex_none, shipped,
    )


class TextTest(SimpleTestCase):
    def test_dates(self):
        self.assertEqual(t.text_date("15.08.17."), date(2017, 8, 15))
        self.assertEqual(t.text_date("19,10,26"), date(2026, 10, 19))
        self.assertEqual(t.text_date("24.06.2021"), date(2021, 6, 24))
        self.assertIsNone(t.text_date("Бакланов"))
        self.assertIsNone(t.text_date("31.02.26"))
        self.assertEqual(t.sewing_dates("в шитье 08.10. отшит 14.10.26"), (date(2026, 10, 8), date(2026, 10, 14)))
        self.assertEqual(t.sewing_dates("в шитье 28.12. отшит 05.01.26"), (date(2025, 12, 28), date(2026, 1, 5)))
        self.assertEqual(t.order_refs("Дуглас Н 1400 диван(№9578)"), [9578])
        self.assertTrue(t.only_sewing("в шитье 08.10. отшит 14.10.26"))
        self.assertFalse(t.only_sewing("в шитье 08.10. отшит 14.10.26 ЕКБ"))
        self.assertEqual(t.clean("Мадрид-1 кровать 1600*200015,10,26"), "Мадрид-1 кровать 1600*2000 15,10,26")

    def test_fabric_names(self):
        self.assertEqual(t.fabric_name("ultra_grafit_4k.jpeg"), "ultra grafit 4k")
        self.assertEqual(t.fabric_name(".\xa0Арбен Ultra cedar "), "Арбен Ultra cedar")
        self.assertEqual(t.fabric_name(".&nbsp;"), "")
        self.assertEqual(t.fabric_name("no photo.jpg"), "")
        self.assertEqual(t.fabric_key("ULTRA_Grafit_4k.JPG"), t.fabric_key("ultra grafit 4k"))
        self.assertEqual(t.quantity("Пуф Бисмарк - 3 штуки"), 3)
        self.assertEqual(t.quantity("Диван Клинт"), 1)


class Model:
    def __init__(self, name):
        self.name = name


class MatcherTest(SimpleTestCase):
    def setUp(self):
        names = ["Пуф Рубик", "Кресло Честер", "Гаити 1600 диван", "Комплект подушек для стула 40*40 2 шт", "Комплект покрывало /2600*1400/ 2 подушки /70*50/ велюр", "Бостон", "Дубай М 1400", "Дубай М 1400 (4 кат.)", "Дубай М кресло", "Аванти Модерн В", "Бисмарк пуф", "Мадрид-2 кровать 1600*2000"]
        self.m = t.ModelMatcher([Model(n) for n in names])

    def check(self, old, model, extra=""):
        found, rest = self.m.match(old)
        self.assertEqual(found.name if found else None, model, old)
        if found:
            self.assertEqual(t.extra_from(rest), extra, old)

    def test_match(self):
        self.check("Дубай М 1400 диван(№9531)", "Дубай М 1400")
        self.check('&nbsp;БД "Дубай М 1400" (4 кат.)', "Дубай М 1400 (4 кат.)")
        self.check('&nbsp;Кресло "Дубай М" (4 кат.)', "Дубай М кресло")
        self.check("Аванти  Модерн B диван (Заказ №8567)27.10.23", "Аванти Модерн В")
        self.check("Пуф Бисмарк - 3 штуки", "Бисмарк пуф")
        self.check("Мадрид-2 кровать 1600*200015,10,26", "Мадрид-2 кровать 1600*2000")
        self.check("Дубай М 1400 диван16,10,26 Накладки белые", "Дубай М 1400", "Накладки белые")
        self.check("Баку диван правый", None)
        self.check("Кресло Бостон", None)
        self.check("Пуф Рубик 25.05.26", "Пуф Рубик")
        self.check("Честер кресло", "Кресло Честер")
        self.check("Гаити 1600 диван 20.10.23", "Гаити 1600 диван")
        self.check("БД Гаити 1600", "Гаити 1600 диван")
        self.check("Комплект подушек для стула 40*40 2 шт.", "Комплект подушек для стула 40*40 2 шт")
        self.check("Комплект покрывало /2600*1400/ 2 подушки /70*50/ велюр", "Комплект покрывало /2600*1400/ 2 подушки /70*50/ велюр")
        self.check("Пуф Бостон - 2 штуки", None)


class DumpTest(SimpleTestCase):
    def test_read(self):
        text = (
            "-- dump\nINSERT INTO `t` (`a`, `b`) VALUES\n(1, 'it\\'s \\\\ ok'),\n(2, NULL);\n"
            "INSERT INTO `other` (`x`) VALUES (5);\nINSERT INTO `t` (`a`, `b`) VALUES (3, 'a, (b); ''c''');\n"
        )
        path = Path(tempfile.mkdtemp()) / "d.sql"
        path.write_text(text, encoding="utf-8")
        rows = read_tables(path, {"t"})["t"]
        self.assertEqual(rows, [{"a": "1", "b": "it's \\ ok"}, {"a": "2", "b": None}, {"a": "3", "b": "a, (b); 'c'"}])
        path.write_text("INSERT INTO `t` (`a`) VALUES (1, 'обрыв", encoding="utf-8")
        with self.assertRaises(DumpError):
            read_tables(path, {"t"})


class ImportLegacyTest(Fixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()
        sofas = Category.objects.get(name="Прямые диваны")
        cls.dubai = ProductModel.objects.create(name="Дубай М 1400", category=sofas)
        cls.dir = Path(tempfile.mkdtemp())

    def write(self, reserv_rows, order_rows):
        reserv = self.dir / "reserv.sql"
        orders = self.dir / "zakaz.sql"
        reserv.write_text("-- reserv\n" + insert("reserv", RESERV_COLS, reserv_rows), encoding="utf-8")
        orders.write_text("-- zakaz\n" + insert("orders", ORDER_COLS, order_rows), encoding="utf-8")
        return str(reserv), str(orders)

    def run_cmd(self, reserv, orders, *args):
        out = StringIO()
        call_command("import_legacy", *args, reserv=reserv, orders=orders, stdout=out)
        return out.getvalue()

    def dumps(self):
        return self.write(
            [
                reserv_row(114542, "Дубай М 1400 диван(№9578)", "4", "ultra_grafit_4k.jpeg", reserve="Агат", reserv_date="19.10.2026"),
                reserv_row(114404, "Бостон диван16,10,26 Накладки белые", "2", comment="в шитье 08.10. отшит 14.10.26", skin="ecotex_213.jpg"),
                reserv_row(114421, "Дубай М 1400 диван", "3", team="Бакланов", work="19,10,26"),
                reserv_row(63605, "Гаити 1600 диван", "1", team="Иванов А.", work="24.06.2021", store="25.06.2021"),
                reserv_row(100, "Бостон СТОП", "2", reserve="СТОП"),
                reserv_row(5436, "Марсель ПРОВЕРЕНО", ""),
            ],
            [
                order_row(9578, "Диван Дубай М 1400", date(2026, 10, 14), tex=date(2026, 10, 19), cut=date(2026, 10, 19)),
                order_row(9386, "Пуф Бостон - 2 штуки", date(2026, 8, 18), man="Ольга Филина"),
                order_row(9409, "Диван Флоренция", date(2026, 9, 1), tex=date(2026, 9, 7), cut=date(2026, 9, 8)),
                order_row(9000, "Диван Бостон", date(2026, 2, 1), shipped="on"),
                order_row(8000, "Диван Бостон", date(2025, 12, 1)),
                order_row(9401, "Диван Бостон", date(2026, 8, 1), comment="заказ снят клиентом"),
                order_row(9402, "Диван Флоренция", date(2026, 9, 20), ip="", main="Велюр 03", tex=date(2026, 9, 25)),
            ],
        )

    def test_dry_run_writes_nothing(self):
        before = (Item.objects.count(), Fabric.objects.count(), Team.objects.count())
        out = self.run_cmd(*self.dumps(), "--dry-run")
        self.assertEqual((Item.objects.count(), Fabric.objects.count(), Team.objects.count()), before)
        self.assertIn("Будет заведено изделий: 7", out)
        self.assertIn("резервы со «СТОП»: 1", out)
        self.assertIn("резервы без склада", out)
        self.assertIn("9409/ЗАК", out)
        self.assertIn("заказы, снятые", out)
        self.assertIn("1 × Гаити 1600 диван", out)
        self.assertNotIn("Менеджер не найден", out)

    def test_import(self):
        reserv, orders = self.dumps()
        out = self.run_cmd(reserv, orders)
        self.assertIn("Заведено изделий: 7", out)
        items = {i.legacy_number: i for i in Item.objects.all()}
        self.assertEqual(sorted(items), ["114404", "114421", "114542 · 9578/ЗАК", "63605", "9386/ЗАК", "9402/ЗАК"])
        self.assertEqual(Item.objects.filter(legacy_number="9386/ЗАК").count(), 2)

        linked = items["114542 · 9578/ЗАК"]
        self.assertEqual((linked.model, linked.stage, linked.reserve), (self.dubai, Stage.CUT, "Агат"))
        self.assertEqual(linked.manager, self.manager)
        self.assertEqual(linked.fabric_arrived_at, date(2026, 10, 19))
        self.assertEqual(timezone.localtime(linked.created_at).date(), date(2026, 10, 14))
        main = linked.fabrics.get(slot="main")
        self.assertEqual((main.fabric.name, main.fabric.active, main.meters), ("ultra grafit 4k", False, None))
        kinds = list(linked.events.order_by("at").values_list("kind", flat=True))
        self.assertEqual(kinds[0], EventKind.CREATED)
        self.assertIn(EventKind.RESERVE, kinds)

        cover = items["114404"]
        self.assertEqual((cover.model, cover.extra, cover.stage), (self.model, "Накладки белые", Stage.COVER))
        self.assertEqual((cover.sew_at, cover.cover_ready_at), (date(2026, 10, 8), date(2026, 10, 14)))
        self.assertEqual(cover.fabrics.get(slot="main").fabric, self.velour)
        self.assertEqual(cover.fabrics.get(slot="comp1").fabric.name, "ecotex 213")
        self.assertEqual(cover.comment, "")
        self.assertIn("«Бостон диван16,10,26 Накладки белые»", cover.events.get(kind=EventKind.CREATED).text)

        work = items["114421"]
        self.assertEqual((work.stage, work.team.name, work.work_at), (Stage.WORK, "Бакланов", date(2026, 10, 19)))
        fg = items["63605"]
        self.assertEqual((fg.custom_name, fg.model, fg.stage, fg.team), ("Гаити 1600 диван", None, Stage.FG, self.team))
        self.assertEqual(timezone.localtime(fg.stage_since).date(), date(2021, 6, 25))
        self.assertEqual(fg.manager.username, "legacy")
        self.assertFalse(fg.manager.is_active)

        order = Item.objects.filter(legacy_number="9386/ЗАК").first()
        self.assertEqual((order.stage, order.reserve, order.manager.username), (Stage.ORDERS, "ИП Петров", "postnikova"))
        self.assertEqual((order.model, order.custom_name), (None, "Пуф Бостон"))
        self.assertEqual(float(order.fabrics.get(slot="main").meters), 12.5)
        no_client = items["9402/ЗАК"]
        self.assertEqual((no_client.stage, no_client.fabric_arrived_at), (Stage.CUT, date(2026, 9, 25)))
        self.assertEqual(no_client.fabrics.get(slot="main").fabric, self.velour)
        self.assertEqual(
            sorted(Item.objects.values_list("number", flat=True)),
            ["114404", "114421", "114542", "63605", "9386/ЗАК", "9386/ЗАК-2", "9402/ЗАК"],
        )
        [new] = s.create_items(self.manager, model=self.model, fabrics=self.fabrics())
        self.assertEqual(new.number, "26/0001")
        linked.extra = "правый угол"
        linked.save()
        self.assertEqual(Item.objects.get(pk=linked.pk).number, "114542")

        again = self.run_cmd(reserv, orders)
        self.assertIn("Заведено изделий: 0", again)
        self.assertIn("уже перенесено раньше (резервы): 4", again)
        self.assertEqual(Item.objects.count(), 8)

    def test_order_imported_then_unit_appears(self):
        reserv, orders = self.write([reserv_row(1, "старая запись", "")], [order_row(9600, "Диван Бостон", date(2026, 10, 1))])
        self.run_cmd(reserv, orders)
        reserv, orders = self.write([reserv_row(115000, "Бостон диван (Заказ №9600)", "4")], [order_row(9600, "Диван Бостон", date(2026, 10, 1))])
        out = self.run_cmd(reserv, orders)
        self.assertIn("резерв 115000: заказ 9600/ЗАК уже перенесён", out)
        self.assertEqual(Item.objects.count(), 1)

    def test_bad_input(self):
        reserv, orders = self.dumps()
        with self.assertRaises(CommandError):
            self.run_cmd(orders, reserv, "--dry-run")
        with self.assertRaises(CommandError):
            self.run_cmd(reserv, orders, "--manager", "без знака")
        with self.assertRaises(CommandError):
            self.run_cmd(reserv, str(self.dir / "nope.sql"))


class FabricMatchTest(Fixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def test_loose_key(self):
        from app_production.legacy.fabrics import loose_key

        same = [
            ("manila 01 001", "Manila 01"),
            ("levis 01 4k 001", "Levis 01"),
            ("kioto dove (4)", "Kioto Dove"),
            ("nevada1", "Nevada 01"),
            ("Levis - 10", "Levis 10"),
            ("ultra cashmere 24072023", "Ultra Cashmere"),
            ("columbia-nut 4k", "Columbia Nut"),
            ("ultra_grafit_4k.jpeg", "Ultra grafit"),
        ]
        for old, new in same:
            self.assertEqual(loose_key(old), loose_key(new), old)
        self.assertNotEqual(loose_key("manila 01 001"), loose_key("Manila 10"))
        self.assertNotEqual(loose_key("nevada 8 001"), loose_key("Nevada 9"))

    def test_relink_and_import_use_renamed_fabrics(self):
        from app_production.legacy.fabrics import FabricMatcher

        manila = Fabric.objects.create(name="Manila 01")
        Fabric.objects.create(name="Manila 10")
        matcher = FabricMatcher(Fabric.objects.all())
        self.assertEqual(matcher.find("manila 01 001"), (manila, True))
        self.assertEqual(matcher.find("Manila 01"), (manila, False))
        self.assertEqual(matcher.find("manila 02 001"), (None, False))

        old = Fabric.objects.create(name="manila 01 001", active=False)
        stray = Fabric.objects.create(name="zzz 5", active=False)
        [item] = s.create_items(self.manager, model=self.model, fabrics=[{"slot": "main", "fabric": self.velour}])
        item.fabrics.all().delete()
        item.fabrics.create(slot="main", fabric=old)
        item.fabrics.create(slot="comp1", fabric=stray)

        out = StringIO()
        call_command("relink_fabrics", "--dry-run", stdout=out)
        self.assertIn("Привязано к тканям справочника: 1", out.getvalue())
        self.assertEqual(item.fabrics.get(slot="main").fabric, old)
        out = StringIO()
        call_command("relink_fabrics", stdout=out)
        self.assertIn("1 × manila 01 001 → Manila 01", out.getvalue())
        self.assertIn("1 × zzz 5", out.getvalue())
        self.assertEqual(item.fabrics.get(slot="main").fabric, manila)
        self.assertFalse(Fabric.objects.filter(pk=old.pk).exists())
        self.assertTrue(Fabric.objects.filter(pk=stray.pk).exists())

    def test_relink_models(self):
        reserv = Path(tempfile.mkdtemp()) / "r.sql"
        orders = reserv.with_name("z.sql")
        reserv.write_text(insert("reserv", RESERV_COLS, [reserv_row(5, "Дуглас 1600 диван 30,07,26 Накладки венге", "2"), reserv_row(6, "Баку диван", "2")]), encoding="utf-8")
        orders.write_text(insert("orders", ORDER_COLS, [order_row(1, "Диван", date(2020, 1, 1))]), encoding="utf-8")
        call_command("import_legacy", reserv=str(reserv), orders=str(orders), stdout=StringIO())
        item = Item.objects.get(number="5")
        self.assertEqual((item.model, item.custom_name), (None, "Дуглас 1600 диван Накладки венге"))

        douglas = ProductModel.objects.create(name="Дуглас 1600", category=self.model.category)
        out = StringIO()
        call_command("relink_models", "--dry-run", stdout=out)
        self.assertIn("Нашлась модель: 1. Осталось вне справочника: 1", out.getvalue())
        self.assertIsNone(Item.objects.get(number="5").model)
        out = StringIO()
        call_command("relink_models", stdout=out)
        self.assertIn("1 × Баку диван", out.getvalue())
        item.refresh_from_db()
        self.assertEqual((item.model, item.custom_name, item.extra), (douglas, "", "Накладки венге"))
        self.assertIn("→ Дуглас 1600", item.events.order_by("-id").first().text)


class NewMatchingTest(SimpleTestCase):
    def test_fabric_words_in_other_order_and_one_typo(self):
        from types import SimpleNamespace as N

        from app_production.legacy.fabrics import FabricMatcher

        fabrics = [N(name=n, photo="x", active=True) for n in ("Kioto 4 dove", "Kioto 6 java", "Safary chesnut", "Monako 05")]
        m = FabricMatcher(fabrics)
        self.assertEqual(m.find("kioto dove (4)")[0].name, "Kioto 4 dove")
        self.assertEqual(m.find("kioto jave (6)")[0].name, "Kioto 6 java")
        self.assertEqual(m.find("safary chestnut 4k")[0].name, "Safary chesnut")
        self.assertIsNone(m.find("monako 4 4k")[0])  # другая цифра — не опечатка

    def test_model_old_names(self):
        from types import SimpleNamespace as N

        models = [N(name=n) for n in ("Кубик-Рубик пуф", "Мюнхен-1 Гранд диван", "Мюнхен-1 XL диван", "Мюнхен-1 ДУ")]
        m = t.ModelMatcher(models)
        self.assertEqual(m.match("Пуф Рубик")[0].name, "Кубик-Рубик пуф")
        self.assertEqual(m.match("Мюнхен Гранд-1 диван правый")[0].name, "Мюнхен-1 Гранд диван")
        self.assertEqual(m.match("Мюнхен XL-1 диван")[0].name, "Мюнхен-1 XL диван")
        model, rest = m.match("Мюнхен-1 диван левый")
        self.assertEqual((model.name, rest), ("Мюнхен-1 ДУ", "левый"))
