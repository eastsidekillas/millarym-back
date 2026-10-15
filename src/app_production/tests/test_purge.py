from datetime import datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from app_production import services as s
from app_production.management.commands.scheduler import next_run
from app_production.models import Item, ItemEvent

from .base import Fixtures


class PurgeTest(Fixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    def setUp(self):
        self.old, self.fresh, self.alive = s.create_items(
            self.manager, model=self.model, fabrics=self.fabrics(), qty=3
        )
        for item in (self.old, self.fresh):
            s.trash(self.director, item.pk)
        Item.objects.filter(pk=self.old.pk).update(trashed_at=timezone.now() - timedelta(days=30))
        Item.objects.filter(pk=self.fresh.pk).update(trashed_at=timezone.now() - timedelta(days=29))
        self.client = APIClient()
        self.client.force_authenticate(self.master)

    def test_purges_only_expired(self):
        self.assertEqual(s.purge_trash(), [self.old.number])
        self.assertFalse(Item.objects.filter(pk=self.old.pk).exists())
        self.assertIsNotNone(Item.all_objects.get(pk=self.old.pk).purged_at)
        self.assertTrue(Item.objects.filter(pk=self.fresh.pk).exists())
        self.assertEqual(s.purge_trash(), [])

    def test_history_stays_and_card_explains(self):
        s.purge_trash()
        self.assertTrue(ItemEvent.objects.filter(item_id=self.old.pk).exists())
        response = self.client.get(f"/api/v1/items/{self.old.pk}/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("удалено из Корзины окончательно", response.json()["detail"])
        events = self.client.get(f"/api/v1/events/?item={self.old.pk}").json()
        self.assertTrue(events["results"])

    def test_purged_hidden_everywhere(self):
        s.purge_trash()
        trash = self.client.get("/api/v1/items/?stage=trash").json()
        self.assertEqual([r["id"] for r in trash["results"]], [self.fresh.pk])
        self.assertEqual(self.client.get("/api/v1/items/counters/").json()["trash"], 1)
        found = self.client.get(f"/api/v1/items/?q={self.old.number}").json()
        self.assertEqual(found["count"], 0)
        self.assertEqual(self.client.get(f"/api/v1/passports/?ids={self.old.pk}").status_code, 404)

    def test_command_dry_run(self):
        out = StringIO()
        call_command("purge_trash", "--dry-run", stdout=out)
        self.assertIn("Удалится из Корзины (лежали больше 30 дн.): 1", out.getvalue())
        self.assertTrue(Item.objects.filter(pk=self.old.pk).exists())
        call_command("purge_trash", stdout=StringIO())
        self.assertFalse(Item.objects.filter(pk=self.old.pk).exists())

    def test_next_run(self):
        tz = ZoneInfo("Asia/Yekaterinburg")
        self.assertEqual(next_run(datetime(2026, 10, 15, 2, 0, tzinfo=tz), "03:00"), datetime(2026, 10, 15, 3, 0, tzinfo=tz))
        self.assertEqual(next_run(datetime(2026, 10, 15, 3, 0, tzinfo=tz), "03:00"), datetime(2026, 10, 16, 3, 0, tzinfo=tz))
