from io import BytesIO

from django.test import TestCase
from openpyxl import load_workbook
from rest_framework.test import APIClient

from app_production import services as s
from app_production.models import Stage
from app_production.tests.base import Fixtures


class ReportsTest(Fixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.master)

    def make(self, **kwargs):
        kwargs.setdefault("model", self.model)
        kwargs.setdefault("fabrics", self.fabrics())
        return s.create_items(self.manager, **kwargs)

    def test_list_of_reports(self):
        kinds = [r["kind"] for r in self.client.get("/api/v1/reports/").json()]
        self.assertEqual(kinds[:2], ["free-stock", "reserved"])

    def test_free_stock_by_models_and_order(self):
        [b] = self.make()
        [f] = self.make(model=self.other_model)
        [c] = self.make(model=None, custom_name="Арка по эскизу")
        self.make(reserve="ИП Петров")
        [t] = self.make()
        s.trash(self.director, t.pk)
        data = self.client.get("/api/v1/reports/free-stock/").json()
        self.assertEqual([r["number"] for r in data["rows"]], [c.number, b.number, f.number])
        self.assertEqual(data["rows"][1]["cells"]["where"], "Крой")
        data = self.client.get(f"/api/v1/reports/free-stock/?models={self.other_model.pk},custom").json()
        self.assertEqual({r["number"] for r in data["rows"]}, {f.number, c.number})
        models = self.client.get("/api/v1/reports/free-stock/models/").json()
        self.assertEqual(models[-1], {"id": "custom", "name": "Вне справочника", "count": 1})

    def test_reserved_groups_and_repeats(self):
        a, b = self.make(reserve="ИП Петров", qty=2)
        [c] = self.make(reserve="ООО Диван")
        [d] = self.make()
        s.set_reserve(self.manager, d.pk, "ип петров (2)")
        s.move(self.director, a.pk, Stage.FG)
        data = self.client.get("/api/v1/reports/reserved/?q=петров").json()
        self.assertEqual(data["total"], 3)
        self.assertEqual([r["mark"] for r in data["rows"]][:2], ["warn", "warn"])
        self.assertEqual(data["rows"][0]["group"], "ИП Петров: 2 шт.")
        self.assertEqual(data["summary"][0]["rows"], [["Бостон", "2"]])
        only_fg = self.client.get("/api/v1/reports/reserved/?q=петров&only_fg=1").json()
        self.assertEqual([r["number"] for r in only_fg["rows"]], [a.number])
        self.assertNotIn(c.number, [r["number"] for r in data["rows"]])

    def test_orders_include_shipped_not_deleted(self):
        [shipped] = self.make(reserve="Фобос")
        [deleted] = self.make(reserve="Фобос")
        s.move(self.director, shipped.pk, Stage.FG)
        s.ship(self.storekeeper, shipped.pk)
        s.trash(self.storekeeper, deleted.pk)
        data = self.client.get("/api/v1/reports/orders-by-reserve/?q=фобос").json()
        self.assertEqual([r["number"] for r in data["rows"]], [shipped.number])
        self.assertTrue(data["rows"][0]["cells"]["where"].startswith("Корзина: отгружено"))

    def test_errors(self):
        self.assertEqual(self.client.get("/api/v1/reports/orders-by-reserve/").status_code, 400)
        self.assertEqual(self.client.get("/api/v1/reports/orders-period/?from=2026-10-10").status_code, 400)
        self.assertEqual(self.client.get("/api/v1/reports/moon/").status_code, 404)

    def test_xlsx_files(self):
        self.make(reserve="ИП Петров")
        self.make()
        for url in ("/api/v1/reports/free-stock/xlsx/", "/api/v1/reports/reserved/xlsx/?q=Петров"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertIn("filename*=UTF-8''", r["Content-Disposition"])
            wb = load_workbook(BytesIO(r.content))
            self.assertIn(wb.active["B1"].value, ("Свободные остатки", "Зарезервированные изделия"))

    def test_single_item_xlsx(self):
        [item] = self.make()
        r = self.client.get(f"/api/v1/items/{item.pk}/export/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("26-", r["Content-Disposition"])
        self.assertEqual(self.client.get("/api/v1/items/999999/export/").status_code, 404)
