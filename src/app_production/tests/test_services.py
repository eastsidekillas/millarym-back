from datetime import date, timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from app_catalog.models import Deadlines
from app_production import services as s
from app_production.errors import ActionError, NoRight
from app_production.models import EventKind, Item, NumberSequence, Stage, TrashReason

from .base import Fixtures


class ServiceTest(Fixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def create(self, user=None, **kwargs):
        kwargs.setdefault("model", self.model)
        kwargs.setdefault("fabrics", self.fabrics())
        return s.create_items(user or self.manager, **kwargs)

    def year(self):
        return timezone.localdate().year % 100

    def kinds(self, item):
        return list(item.events.order_by("id").values_list("kind", flat=True))


class CreateTest(ServiceTest):
    def test_reserve_goes_to_orders_free_goes_to_cut(self):
        [ordered] = self.create(reserve="  ИП Петров  ")
        [stock] = self.create()
        self.assertEqual((ordered.stage, ordered.reserve), (Stage.ORDERS, "ИП Петров"))
        self.assertIsNotNone(ordered.reserved_at)
        self.assertEqual(stock.stage, Stage.CUT)
        self.assertIsNone(stock.reserved_at)
        self.assertEqual(ordered.number, f"{self.year():02d}/0001")
        self.assertEqual(stock.number, f"{self.year():02d}/0002")
        self.assertEqual(self.kinds(stock), [EventKind.CREATED])
        self.assertEqual(stock.manager, self.manager)

    def test_qty_gives_consecutive_numbers(self):
        items = self.create(qty=3)
        self.assertEqual([i.seq for i in items], [1, 2, 3])
        self.assertEqual(Item.objects.filter(fabrics__slot="main").count(), 3)
        for qty in (0, 51):
            with self.assertRaises(ActionError):
                self.create(qty=qty)

    def test_five_digits_after_9999(self):
        NumberSequence.objects.create(period=timezone.localdate().year, last_value=9999)
        [item] = self.create()
        self.assertEqual(item.number, f"{self.year():02d}/10000")

    def test_new_year_starts_from_one(self):
        self.create()
        next_year = date(timezone.localdate().year + 1, 1, 1)
        with mock.patch("app_production.numbering.timezone.localdate", return_value=next_year):
            [item] = self.create()
        self.assertEqual(item.number, f"{next_year.year % 100:02d}/0001")

    def test_fabric_rules(self):
        with self.assertRaisesMessage(ActionError, "основную ткань"):
            self.create(fabrics=[{"slot": "comp1", "fabric": self.velour}])
        with self.assertRaisesMessage(ActionError, "один раз"):
            self.create(fabrics=self.fabrics() + [{"slot": "main", "fabric": self.leather}])
        self.leather.active = False
        self.leather.save()
        with self.assertRaisesMessage(ActionError, "скрыта"):
            self.create(fabrics=self.fabrics(comp2=self.leather))
        self.assertFalse(Item.objects.exists())

    def test_inactive_model(self):
        self.model.active = False
        self.model.save()
        with self.assertRaisesMessage(ActionError, "скрыта"):
            self.create()

    def test_rights(self):
        with self.assertRaisesMessage(NoRight, "Могут:"):
            self.create(user=self.master)
        self.create(user=self.cutter)

    def test_indiv_due_date(self):
        [item] = self.create(indiv=True, indiv_note="усиленный каркас")
        self.assertEqual(item.due_at, timezone.localdate() + timedelta(days=30))
        [plain] = self.create(indiv_note="не сохранится")
        self.assertIsNone(plain.due_at)
        self.assertEqual(plain.indiv_note, "")


class MoveTest(ServiceTest):
    def test_full_path_by_responsible_people(self):
        [item] = self.create(reserve="ООО Диван")
        s.move(self.cutter, item.pk, Stage.CUT)
        item = s.move(self.cutter, item.pk, Stage.COVER)
        today = timezone.localdate()
        self.assertEqual((item.sew_at, item.cover_ready_at), (today, today))
        with self.assertRaisesMessage(ActionError, "нужна бригада"):
            s.move(self.master, item.pk, Stage.WORK)
        item = s.move(self.master, item.pk, Stage.WORK, team=self.team)
        self.assertEqual((item.team, item.work_at), (self.team, today))
        s.move(self.master, item.pk, Stage.FG)
        item = s.ship(self.storekeeper, item.pk)
        self.assertEqual(item.trash_reason, TrashReason.SHIPPED)
        self.assertTrue(item.in_trash)
        item = s.restore(self.cutter, item.pk)
        self.assertEqual((item.stage, item.in_trash), (Stage.FG, False))
        self.assertEqual(
            self.kinds(item),
            ["created", "move", "move", "move", "move", "ship", "restore"],
        )
        texts = list(item.events.order_by("id").values_list("text", flat=True))
        self.assertIn("Склад чехлов → В работе, бригада Бригада Иванова", texts)

    def test_each_step_needs_its_right(self):
        [item] = self.create(reserve="Х")
        for user in (self.manager, self.master, self.storekeeper):
            with self.assertRaises(NoRight):
                s.move(user, item.pk, Stage.CUT)
        s.move(self.cutter, item.pk, Stage.CUT)
        s.move(self.cutter, item.pk, Stage.COVER)
        with self.assertRaises(NoRight):
            s.move(self.cutter, item.pk, Stage.WORK, team=self.team)

    def test_skip_needs_move_any(self):
        [item] = self.create()
        with self.assertRaisesMessage(NoRight, "Юлдашева О."):
            s.move(self.cutter, item.pk, Stage.FG)
        item = s.move(self.director, item.pk, Stage.FG)
        self.assertEqual(item.stage, Stage.FG)
        self.assertIsNotNone(item.cover_ready_at)
        item = s.move(self.director, item.pk, Stage.CUT)
        self.assertEqual(item.stage, Stage.CUT)
        with self.assertRaisesMessage(ActionError, "«Заказы»"):
            s.move(self.director, item.pk, Stage.ORDERS)

    def test_same_stage_and_unknown_stage(self):
        [item] = self.create()
        with self.assertRaisesMessage(ActionError, "уже на этапе"):
            s.move(self.director, item.pk, Stage.CUT)
        with self.assertRaises(ActionError):
            s.move(self.director, item.pk, "moon")

    def test_trashed_item_is_frozen(self):
        [item] = self.create()
        s.trash(self.storekeeper, item.pk)
        for action in (
            lambda: s.move(self.director, item.pk, Stage.COVER),
            lambda: s.set_reserve(self.director, item.pk, "Х"),
            lambda: s.mark_sew(self.director, item.pk),
            lambda: s.update_item(self.director, item.pk, comment="x"),
            lambda: s.trash(self.director, item.pk),
        ):
            with self.assertRaisesMessage(ActionError, "в Корзине"):
                action()
        item = s.restore(self.director, item.pk)
        self.assertEqual(item.stage, Stage.CUT)

    def test_ship_only_from_fg(self):
        [item] = self.create()
        with self.assertRaisesMessage(ActionError, "только с СГП"):
            s.ship(self.storekeeper, item.pk)
        with self.assertRaises(NoRight):
            s.ship(self.manager, item.pk)

    def test_trash_and_restore_rights(self):
        [item] = self.create()
        for user in (self.manager, self.cutter, self.master):
            with self.assertRaises(NoRight):
                s.trash(user, item.pk)
        item = s.trash(self.storekeeper, item.pk)
        self.assertEqual(item.trash_reason, TrashReason.DELETED)
        for user in (self.manager, self.master):
            with self.assertRaises(NoRight):
                s.restore(user, item.pk)
        with self.assertRaisesMessage(ActionError, "не в Корзине"):
            s.restore(self.cutter, s.restore(self.cutter, item.pk).pk)

    def test_bulk_move_all_or_nothing(self):
        items = self.create(qty=3)
        s.move(self.cutter, items[2].pk, Stage.COVER)
        with self.assertRaisesMessage(ActionError, "уже на этапе"):
            s.bulk_move(self.cutter, [i.pk for i in items], Stage.COVER)
        self.assertEqual(Item.objects.filter(stage=Stage.COVER).count(), 1)
        moved = s.bulk_move(self.cutter, [i.pk for i in items[:2]], Stage.COVER)
        self.assertEqual(len(moved), 2)
        moved = s.bulk_move(self.master, [i.pk for i in items], Stage.WORK, team=self.team)
        self.assertTrue(all(i.team == self.team for i in moved))
        with self.assertRaises(ActionError):
            s.bulk_move(self.master, [], Stage.FG)

    def test_return_to_work(self):
        [item] = self.create()
        s.move(self.director, item.pk, Stage.WORK, team=self.team)
        with self.assertRaisesMessage(ActionError, "только с СГП"):
            s.return_to_work(self.master, item.pk)
        s.move(self.master, item.pk, Stage.FG)
        with self.assertRaises(NoRight):
            s.return_to_work(self.storekeeper, item.pk)
        item = s.return_to_work(self.master, item.pk)
        self.assertEqual((item.stage, item.team), (Stage.WORK, self.team))
        self.assertEqual(self.kinds(item)[-1], EventKind.RETURN_TO_WORK)


class MarksTest(ServiceTest):
    def test_fabric_arrived_only_on_orders_once(self):
        [ordered] = self.create(reserve="Х")
        [stock] = self.create()
        with self.assertRaises(NoRight):
            s.mark_fabric_arrived(self.manager, ordered.pk)
        item = s.mark_fabric_arrived(self.cutter, ordered.pk)
        self.assertEqual(item.fabric_arrived_at, timezone.localdate())
        with self.assertRaisesMessage(ActionError, "уже отмечено"):
            s.mark_fabric_arrived(self.cutter, ordered.pk)
        with self.assertRaisesMessage(ActionError, "«Заказы»"):
            s.mark_fabric_arrived(self.cutter, stock.pk)

    def test_cover_ready_stays_on_cut_and_fills_sew(self):
        [item] = self.create()
        item = s.mark_cover_ready(self.cutter, item.pk)
        self.assertEqual(item.stage, Stage.CUT)
        self.assertEqual(item.sew_at, item.cover_ready_at)
        with self.assertRaisesMessage(ActionError, "уже отмечено"):
            s.mark_sew(self.cutter, item.pk)

    def test_sew_then_cover(self):
        [item] = self.create()
        s.mark_sew(self.cutter, item.pk)
        s.mark_cover_ready(self.cutter, item.pk)
        self.assertEqual(self.kinds(Item.objects.get(pk=item.pk))[1:], [EventKind.SEW, EventKind.COVER_READY])


class ReserveTest(ServiceTest):
    def test_reserve_lifecycle(self):
        [item] = self.create()
        item = s.set_reserve(self.manager, item.pk, " ООО Мебель ")
        self.assertEqual((item.stage, item.reserve), (Stage.CUT, "ООО Мебель"))
        first = item.reserved_at
        self.assertIsNotNone(first)
        item = s.set_reserve(self.manager, item.pk, "ООО Мебель-2")
        self.assertEqual(item.reserved_at, first)
        events = item.events.count()
        s.set_reserve(self.manager, item.pk, "ООО Мебель-2")
        self.assertEqual(item.events.count(), events)
        item = s.set_reserve(self.cutter, item.pk, "")
        self.assertIsNone(item.reserved_at)
        self.assertEqual(
            list(item.events.filter(kind="reserve").order_by("id").values_list("text", flat=True)),
            ["Резерв: «ООО Мебель»", "Резерв: «ООО Мебель» → «ООО Мебель-2»", "Резерв снят (был «ООО Мебель-2»)"],
        )

    def test_who_cannot_reserve(self):
        [item] = self.create()
        for user in (self.master, self.storekeeper):
            with self.assertRaises(NoRight):
                s.set_reserve(user, item.pk, "Х")


class EditCopyTest(ServiceTest):
    def test_edit_logs_each_field(self):
        [item] = self.create(extra="левый угол")
        item = s.update_item(self.manager, item.pk, model=self.other_model, extra="правый угол", comment="")
        texts = list(item.events.filter(kind="edit").order_by("id").values_list("text", flat=True))
        self.assertEqual(texts, ["Название: Бостон → Флоренция", "Комплектация: левый угол → правый угол"])

    def test_edit_on_any_stage(self):
        [item] = self.create(extra="левый угол")
        s.move(self.director, item.pk, Stage.WORK, team=self.team)
        item = s.update_item(
            self.cutter, item.pk, model=self.other_model, extra="правый угол, накладки венге",
            fabrics=self.fabrics(comp2=self.leather),
        )
        self.assertEqual((item.stage, item.title, item.extra), (Stage.WORK, "Флоренция", "правый угол, накладки венге"))
        self.assertEqual(item.fabrics.count(), 2)

    def test_custom_name(self):
        [item] = self.create(model=None, custom_name="  Диван «Каприз» по эскизу  ")
        self.assertEqual((item.model, item.title), (None, "Диван «Каприз» по эскизу"))
        with self.assertRaisesMessage(ActionError, "впишите название"):
            self.create(model=None, custom_name=" ")
        item = s.update_item(self.manager, item.pk, model=self.model)
        self.assertEqual((item.title, item.custom_name), ("Бостон", ""))
        item = s.update_item(self.manager, item.pk, model=None, custom_name="Бостон XL")
        self.assertEqual(item.title, "Бостон XL")
        texts = list(item.events.filter(kind="edit").order_by("id").values_list("text", flat=True))
        self.assertEqual(texts, ["Название: Диван «Каприз» по эскизу → Бостон", "Название: Бостон → Бостон XL (вне справочника)"])
        copy = s.copy_item(self.manager, item.pk)
        self.assertEqual(copy.title, "Бостон XL")

    def test_hidden_model_stays_on_existing_item(self):
        [item] = self.create()
        self.model.active = False
        self.model.save()
        item = s.update_item(self.manager, item.pk, model=self.model, extra="левый угол")
        self.assertEqual(item.extra, "левый угол")

    def test_indiv_toggle_sets_due(self):
        [item] = self.create()
        item = s.update_item(self.manager, item.pk, indiv=True, indiv_note="ниже на 5 см")
        self.assertEqual(item.due_at, timezone.localtime(item.created_at).date() + timedelta(days=30))
        item = s.update_item(self.manager, item.pk, indiv=False)
        self.assertIsNone(item.due_at)
        self.assertEqual(item.indiv_note, "")

    def test_fabrics_replace(self):
        [item] = self.create()
        s.update_item(self.manager, item.pk, fabrics=self.fabrics(comp2=self.leather))
        self.assertEqual(item.fabrics.count(), 2)
        last = item.events.order_by("-id").first()
        self.assertEqual(last.text, "Ткани: Основа: Велюр 03 12 м → Основа: Велюр 03 12 м; Компаньон 2: Экокожа белая")

    def test_meters_text(self):
        self.assertEqual(s.meters_text(12.5), "12,5 м")
        self.assertEqual(s.meters_text("3.00"), "3 м")

    def test_edit_rules(self):
        [item] = self.create()
        with self.assertRaises(NoRight):
            s.update_item(self.master, item.pk, comment="x")
        with self.assertRaisesMessage(ActionError, "Нельзя менять"):
            s.update_item(self.manager, item.pk, stage=Stage.FG)

    def test_copy(self):
        [item] = self.create(reserve="ИП Сидоров", extra="левый угол", fabrics=self.fabrics(comp2=self.leather))
        copy = s.copy_item(self.manager, item.pk)
        self.assertNotEqual(copy.number, item.number)
        self.assertEqual((copy.stage, copy.reserve, copy.extra), (Stage.ORDERS, "ИП Сидоров", "левый угол"))
        self.assertEqual(copy.fabrics.count(), 2)
        self.assertEqual(item.events.order_by("-id").first().text, f"Скопировано в {copy.number}")
        self.assertEqual(copy.events.get().text, f"Копия {item.number} → Заказы")


class WarningsTest(ServiceTest):
    def test_only_indiv_and_by_days(self):
        [item] = self.create(reserve="Х", indiv=True)
        [plain] = self.create(reserve="Х")
        d = Deadlines.get()
        created = timezone.localtime(item.created_at).date()
        self.assertEqual(item.warnings(created + timedelta(days=10), d), [])
        self.assertEqual(item.warnings(created + timedelta(days=11), d), ["fabric"])
        self.assertEqual(item.warnings(created + timedelta(days=21), d), ["fabric", "cut"])
        self.assertEqual(item.warnings(created + timedelta(days=31), d), ["fabric", "cut", "output"])
        self.assertEqual(plain.warnings(created + timedelta(days=60), d), [])
        item.stage = Stage.FG
        self.assertEqual(item.warnings(created + timedelta(days=60), d), [])
