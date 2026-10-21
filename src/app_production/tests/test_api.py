from datetime import timedelta
from unittest import skipUnless

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from app_production import services as s
from app_production.models import Item, Stage

from .base import Fixtures


class ApiTest(Fixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def make(self, qty=1, **kwargs):
        kwargs.setdefault("model", self.model)
        kwargs.setdefault("fabrics", self.fabrics())
        return s.create_items(self.manager, qty=qty, **kwargs)

    def body(self, **kwargs):
        data = {"model": self.model.pk, "fabrics": [{"slot": "main", "fabric": self.velour.pk, "meters": "12.5"}]}
        data.update(kwargs)
        return data


class ListTest(ApiTest):
    def test_closed_without_login(self):
        self.assertEqual(APIClient().get("/api/v1/items/").status_code, 401)

    def test_stage_tabs_and_trash(self):
        [ordered] = self.make(reserve="ИП Петров")
        stock = self.make(qty=2)
        s.trash(self.director, stock[0].pk)
        client = self.as_user(self.master)

        orders = client.get("/api/v1/items/?stage=orders").json()
        self.assertEqual([i["number"] for i in orders["results"]], [ordered.number])
        row = orders["results"][0]
        self.assertEqual(row["stage_label"], "Заказы")
        self.assertEqual(row["model"], {"id": self.model.pk, "name": "Бостон"})
        self.assertEqual(row["fabrics"][0]["fabric"]["name"], "Велюр 03")
        self.assertEqual(row["fabrics"][0]["slot_label"], "Основа")
        self.assertEqual(row["manager"], "Окишева Е.")

        self.assertEqual(client.get("/api/v1/items/?stage=cut").json()["count"], 1)
        trash = client.get("/api/v1/items/?stage=trash").json()["results"]
        self.assertEqual(len(trash), 1)
        self.assertEqual(trash[0]["trash_reason"], "deleted")
        self.assertEqual(trash[0]["purge_at"], str(timezone.localdate() + timedelta(days=30)))
        self.assertEqual(client.get("/api/v1/items/?stage=moon").status_code, 400)

    def test_filters(self):
        [ordered] = self.make(reserve="ИП Петров", indiv=True)
        [free] = self.make()
        [reserved_stock] = self.make()
        s.set_reserve(self.manager, reserved_stock.pk, "ООО Диван")
        [other] = self.make(model=self.other_model)
        client = self.as_user(self.manager)

        def numbers(query):
            return sorted(i["number"] for i in client.get(f"/api/v1/items/?{query}").json()["results"])

        self.assertEqual(numbers("free=1"), sorted([free.number, other.number]))
        self.assertEqual(numbers("reserved=true"), sorted([ordered.number, reserved_stock.number]))
        self.assertEqual(numbers("indiv=1"), [ordered.number])
        self.assertEqual(numbers(f"model={self.other_model.pk}"), [other.number])
        self.assertEqual(numbers(f"model={self.model.pk},{self.other_model.pk}&stage=cut"), sorted([free.number, reserved_stock.number, other.number]))

    def test_late_filter(self):
        [late] = self.make(reserve="Х", indiv=True)
        [fresh] = self.make(reserve="Х", indiv=True)
        [plain] = self.make(reserve="Х")
        old = timezone.now() - timedelta(days=12)
        Item.objects.filter(pk__in=[late.pk, plain.pk]).update(created_at=old)
        rows = self.as_user(self.manager).get("/api/v1/items/?late=1").json()["results"]
        self.assertEqual([r["number"] for r in rows], [late.number])
        self.assertEqual(rows[0]["warnings"], ["fabric"])
        self.assertNotIn(fresh.number, [r["number"] for r in rows])

    def test_search(self):
        [a] = self.make(reserve="ООО Ромашка", extra="левый угол")
        [b] = self.make(model=self.other_model, fabrics=self.fabrics(comp2=self.leather))
        s.move(self.director, b.pk, Stage.WORK, team=self.team)
        client = self.as_user(self.manager)

        def found(text):
            return [i["number"] for i in client.get("/api/v1/items/", {"q": text}).json()["results"]]

        self.assertEqual(found("Ромашка"), [a.number])
        self.assertEqual(found("левый"), [a.number])
        self.assertEqual(found("Флоренция"), [b.number])
        self.assertEqual(found("Экокожа"), [b.number])
        self.assertEqual(found("Иванова"), [b.number])
        self.assertEqual(found(a.number), [a.number])
        self.assertEqual(found(str(b.seq)), [b.number])
        self.assertEqual(found("нет такого"), [])

    @skipUnless(connection.vendor == "postgresql", "SQLite не сравнивает кириллицу без учёта регистра")
    def test_search_ignores_case(self):
        [a] = self.make(reserve="ООО Ромашка")
        rows = self.as_user(self.manager).get("/api/v1/items/", {"q": "ромашка"}).json()["results"]
        self.assertEqual([r["number"] for r in rows], [a.number])

    def test_search_includes_trash_last(self):
        [a] = self.make(reserve="Петров")
        [b] = self.make()
        s.set_reserve(self.manager, b.pk, "Петров")
        [c] = self.make(reserve="Петров")
        s.trash(self.director, c.pk)
        client = self.as_user(self.manager)
        rows = client.get("/api/v1/items/", {"q": "Петров"}).json()["results"]
        self.assertEqual(sorted(r["number"] for r in rows[:2]), sorted([a.number, b.number]))
        self.assertEqual(rows[2]["number"], c.number)
        trash = client.get("/api/v1/items/", {"q": "Петров", "stage": "trash"}).json()["results"]
        self.assertEqual([r["number"] for r in trash], [c.number])
        self.assertEqual(client.get("/api/v1/items/").json()["count"], 2)

    def test_list_query_count_is_flat(self):
        self.make(qty=5, fabrics=self.fabrics(comp2=self.leather))
        client = self.as_user(self.manager)
        client.get("/api/v1/items/")
        with CaptureQueriesContext(connection) as small:
            client.get("/api/v1/items/")
        self.make(qty=20, fabrics=self.fabrics(comp2=self.leather))
        with CaptureQueriesContext(connection) as big:
            client.get("/api/v1/items/")
        self.assertEqual(len(small), len(big))

    def test_counters(self):
        self.make(reserve="Х", qty=2)
        stock = self.make(qty=3)
        s.trash(self.director, stock[0].pk)
        [late] = self.make(reserve="Х", indiv=True)
        Item.objects.filter(pk=late.pk).update(created_at=timezone.now() - timedelta(days=15))
        data = self.as_user(self.master).get("/api/v1/items/counters/").json()
        self.assertEqual(data["stages"]["orders"], {"total": 3, "late": 1})
        self.assertEqual(data["stages"]["cut"], {"total": 2, "late": 0})
        self.assertEqual(data["stages"]["fg"], {"total": 0, "late": 0})
        self.assertEqual((data["free"], data["trash"], data["late"]), (2, 1, 1))


class ActionApiTest(ApiTest):
    def test_create(self):
        r = self.as_user(self.manager).post("/api/v1/items/", self.body(reserve="ИП Петров", qty=2), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual([i["stage"] for i in r.json()], ["orders", "orders"])
        self.assertEqual(r.json()[0]["fabrics"][0]["meters"], "12.50")

    def test_create_custom_name_and_search(self):
        body = self.body(custom_name="Угловой по эскизу 3,2 м")
        body.pop("model")
        r = self.as_user(self.manager).post("/api/v1/items/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.json()[0]["model"], r.json()[0]["title"]), (None, "Угловой по эскизу 3,2 м"))
        rows = self.as_user(self.manager).get("/api/v1/items/", {"q": "эскизу"}).json()["results"]
        self.assertEqual(len(rows), 1)
        item_id = r.json()[0]["id"]
        r = self.as_user(self.manager).patch(f"/api/v1/items/{item_id}/", {"model": self.model.pk}, format="json")
        self.assertEqual(r.json()["title"], "Бостон")
        r = self.as_user(self.manager).post("/api/v1/items/", {"fabrics": body["fabrics"]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_create_validation(self):
        client = self.as_user(self.manager)
        r = client.post("/api/v1/items/", self.body(fabrics=[]), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("основную ткань", r.json()["detail"])
        r = client.post("/api/v1/items/", self.body(qty=51), format="json")
        self.assertIn("qty", r.json()["errors"])
        r = client.post("/api/v1/items/", self.body(model=999999), format="json")
        self.assertIn("model", r.json()["errors"])

    def test_create_forbidden(self):
        r = self.as_user(self.master).post("/api/v1/items/", self.body(), format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("Могут:", r.json()["detail"])
        self.assertFalse(Item.objects.exists())

    def test_detail_has_history_and_actions(self):
        [item] = self.make()
        data = self.as_user(self.cutter).get(f"/api/v1/items/{item.pk}/").json()
        self.assertEqual(data["events"][0]["text"], "Заведено → Крой")
        self.assertEqual(data["events"][0]["user"]["name"], "Окишева Е.")
        actions = {a["code"]: a for a in data["actions"]}
        self.assertEqual(actions["move"]["to"], "cover")
        self.assertTrue(actions["move"]["allowed"])
        self.assertIn("sew", actions)
        self.assertFalse(actions["trash"]["allowed"])
        self.assertIn("Вознесенская Н.", actions["trash"]["reason"])

        master = {a["code"]: a for a in self.as_user(self.master).get(f"/api/v1/items/{item.pk}/").json()["actions"]}
        self.assertFalse(master["move"]["allowed"])

    def test_actions_in_trash(self):
        [item] = self.make()
        s.trash(self.director, item.pk)
        data = self.as_user(self.cutter).get(f"/api/v1/items/{item.pk}/").json()
        self.assertEqual([a["code"] for a in data["actions"]], ["restore"])

    def test_full_flow_over_http(self):
        [item] = self.make(reserve="ООО Диван")
        url = f"/api/v1/items/{item.pk}"
        cutter, master, store = self.as_user(self.cutter), self.as_user(self.master), self.as_user(self.storekeeper)
        self.assertEqual(cutter.post(f"{url}/fabric-arrived/").json()["fabric_arrived_at"], str(timezone.localdate()))
        self.assertEqual(cutter.post(f"{url}/move/", {"to": "cut"}).json()["stage"], "cut")
        cutter.post(f"{url}/sew/")
        cutter.post(f"{url}/cover-ready/")
        self.assertEqual(cutter.post(f"{url}/move/", {"to": "cover"}).json()["stage"], "cover")
        r = master.post(f"{url}/move/", {"to": "work"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("бригада", r.json()["detail"])
        r = master.post(f"{url}/move/", {"to": "work", "team": self.team.pk})
        self.assertEqual(r.json()["team"], {"id": self.team.pk, "name": "Бригада Иванова"})
        master.post(f"{url}/move/", {"to": "fg"})
        self.assertEqual(master.post(f"{url}/return-to-work/").json()["stage"], "work")
        master.post(f"{url}/move/", {"to": "fg"})
        r = store.post(f"{url}/ship/")
        self.assertEqual((r.json()["trash_reason"], r.json()["stage"]), ("shipped", "fg"))
        self.assertEqual(cutter.post(f"{url}/restore/").json()["trashed_at"], None)
        self.assertEqual(len(cutter.get(f"{url}/").json()["events"]), 12)

    def test_forbidden_move_message(self):
        [item] = self.make(reserve="Х")
        r = self.as_user(self.manager).post(f"/api/v1/items/{item.pk}/move/", {"to": "cut"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("Котомцева С.", r.json()["detail"])

    def test_reserve_edit_copy_trash(self):
        [item] = self.make()
        url = f"/api/v1/items/{item.pk}"
        client = self.as_user(self.manager)
        self.assertEqual(client.post(f"{url}/reserve/", {"reserve": "ИП Иванов"}).json()["reserve"], "ИП Иванов")
        r = client.patch(f"{url}/", {"comment": "срочно", "fabrics": [{"slot": "main", "fabric": self.leather.pk}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["comment"], "срочно")
        self.assertEqual(r.json()["fabrics"][0]["fabric"]["name"], "Экокожа белая")
        r = client.post(f"{url}/copy/")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["stage"], "orders")
        self.assertEqual(client.post(f"{url}/trash/").status_code, 403)
        self.assertEqual(self.as_user(self.storekeeper).post(f"{url}/trash/").json()["trash_reason"], "deleted")

    def test_bulk_move(self):
        items = self.make(qty=3)
        ids = [i.pk for i in items]
        r = self.as_user(self.cutter).post("/api/v1/items/bulk-move/", {"ids": ids, "to": "cover"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({i["stage"] for i in r.json()}, {"cover"})
        r = self.as_user(self.master).post("/api/v1/items/bulk-move/", {"ids": ids, "to": "work"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Item.objects.filter(stage=Stage.WORK).count(), 0)

    def test_unknown_item(self):
        r = self.as_user(self.director).post("/api/v1/items/999999/move/", {"to": "cover"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.as_user(self.director).get("/api/v1/items/999999/").status_code, 404)


class EventsApiTest(ApiTest):
    def test_journal_filters(self):
        [a] = self.make(reserve="ООО Ромашка")
        [b] = self.make()
        s.move(self.cutter, b.pk, Stage.COVER)
        client = self.as_user(self.master)
        all_events = client.get("/api/v1/events/").json()
        self.assertEqual(all_events["count"], 3)
        self.assertEqual(all_events["results"][0]["text"], "Крой → Склад чехлов")
        self.assertEqual(all_events["results"][0]["item"], {"id": b.pk, "number": b.number})
        self.assertEqual(client.get(f"/api/v1/events/?user={self.cutter.pk}").json()["count"], 1)
        self.assertEqual(client.get(f"/api/v1/events/?item={a.pk}").json()["count"], 1)
        self.assertEqual(client.get("/api/v1/events/?q=Ромашка").json()["count"], 1)
        self.assertEqual(client.get("/api/v1/events/?kind=move").json()["count"], 1)
        today = timezone.localdate()
        self.assertEqual(client.get(f"/api/v1/events/?from={today}&to={today}").json()["count"], 3)
        self.assertEqual(client.get(f"/api/v1/events/?to={today - timedelta(days=1)}").json()["count"], 0)
        self.assertEqual(client.get("/api/v1/events/?from=вчера").status_code, 400)

    def test_users_list(self):
        rows = self.as_user(self.master).get("/api/v1/users/").json()
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0]["short_name"], "Вознесенская Н.")


class CancelOrderTest(ApiTest):
    def test_cancel_only_on_orders(self):
        [order] = self.make(reserve="ИП Петров")
        [stock] = self.make()
        client = self.as_user(self.manager)
        actions = {a["code"]: a for a in client.get(f"/api/v1/items/{order.pk}/").json()["actions"]}
        self.assertTrue(actions["cancel"]["allowed"])
        self.assertNotIn("cancel", {a["code"] for a in client.get(f"/api/v1/items/{stock.pk}/").json()["actions"]})

        r = client.post(f"/api/v1/items/{stock.pk}/cancel/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("уберите резерв", r.json()["detail"])
        self.assertEqual(self.as_user(self.master).post(f"/api/v1/items/{order.pk}/cancel/").status_code, 403)

        data = client.post(f"/api/v1/items/{order.pk}/cancel/").json()
        self.assertEqual((data["trash_reason"], data["trash_reason_label"]), ("cancelled", "Заказ снят"))
        self.assertEqual(data["events"][0]["text"], "Заказ снят (резерв был «ИП Петров»)")
        trash = client.get("/api/v1/items/?stage=trash").json()["results"]
        self.assertEqual([i["trash_reason_label"] for i in trash], ["Заказ снят"])
        restored = self.as_user(self.director).post(f"/api/v1/items/{order.pk}/restore/").json()
        self.assertEqual((restored["stage"], restored["reserve"]), ("orders", "ИП Петров"))
        self.assertIn("заказ снят", restored["events"][0]["text"])


class OrderingTest(ApiTest):
    def test_stage_tabs_alphabetical_orders_by_date(self):
        from app_catalog.models import ProductModel

        cat = self.model.category
        yolka = ProductModel.objects.create(name="Ёлка", category=cat)
        arka = ProductModel.objects.create(name="арка", category=cat)
        [b] = self.make()
        [y] = self.make(model=yolka)
        [c] = self.make(model=None, custom_name="Диван по эскизу")
        [a2] = self.make(model=arka, extra="правый угол")
        [a1] = self.make(model=arka, extra="левый угол")
        client = self.as_user(self.manager)
        rows = client.get("/api/v1/items/?stage=cut").json()["results"]
        self.assertEqual([r["number"] for r in rows], [a1.number, a2.number, b.number, c.number, y.number])

        o1, o2 = self.make(reserve="ИП Петров"), self.make(reserve="ООО Агат")
        rows = client.get("/api/v1/items/?stage=orders").json()["results"]
        self.assertEqual([r["number"] for r in rows], [o2[0].number, o1[0].number])
        rows = client.get("/api/v1/items/?stage=cut&ordering=recent").json()["results"]
        self.assertEqual(rows[0]["number"], a1.number)
