import threading
from unittest import skipUnless

from django.db import connection, connections
from django.test import TransactionTestCase

from app_production import services as s
from app_production.models import Item

from .base import Fixtures


@skipUnless(connection.vendor == "postgresql", "Блокировки строк проверяются только на PostgreSQL")
class NumberingRaceTest(Fixtures, TransactionTestCase):
    def setUp(self):
        self.make_fixtures()

    def test_parallel_creation_gives_unique_consecutive_numbers(self):
        threads_count, per_thread = 8, 5
        barrier = threading.Barrier(threads_count)
        errors = []

        def worker():
            try:
                barrier.wait()
                for _ in range(per_thread):
                    s.create_items(self.manager, model=self.model, fabrics=self.fabrics())
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(threads_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        seqs = sorted(Item.objects.values_list("seq", flat=True))
        self.assertEqual(seqs, list(range(1, threads_count * per_thread + 1)))
