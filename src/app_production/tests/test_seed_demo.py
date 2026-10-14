from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from app_production.models import Item, ItemEvent


class SeedDemoTest(TestCase):
    def test_refuses_without_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_creates_items_with_history_once(self):
        call_command("seed_demo", items=12, stdout=StringIO())
        self.assertEqual(Item.objects.count(), 12)
        self.assertTrue(ItemEvent.objects.exists())
        with self.assertRaises(CommandError):
            call_command("seed_demo", items=1, stdout=StringIO())
        call_command("seed_demo", items=3, append=True, stdout=StringIO())
        self.assertEqual(Item.objects.count(), 15)
