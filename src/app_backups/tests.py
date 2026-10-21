import os
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from app_auth.models import User
from app_production.tests.base import Fixtures

from . import store


class BackupsTest(Fixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()
        cls.admin = User.objects.create_user("sysadmin", password="x", last_name="Сисадминов", first_name="И.")
        cls.admin.groups.add(Group.objects.get(name="Сисадмин"))

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        override = override_settings(BACKUP_ROOT=self.root, BACKUP_ACCEL="")
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self.dir.cleanup)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def beat(self):
        (self.root / ".control").mkdir(exist_ok=True)
        (self.root / ".control" / "heartbeat").touch()

    def copy(self, stamp, note=None, media=True):
        (self.root / f"db_{stamp}.dump").write_bytes(b"x" * 10)
        if media:
            (self.root / f"media_{stamp}.tar.gz").write_bytes(b"y" * 5)
        if note:
            (self.root / f"note_{stamp}.txt").write_text(note, encoding="utf-8")

    def test_only_sysadmin(self):
        self.assertNotIn("backups", self.director.rights)
        self.assertEqual(self.admin.rights, ["backups"])
        other = APIClient()
        other.force_authenticate(self.director)
        self.assertEqual(other.get("/api/v1/backups/").status_code, 403)

    def test_list_and_alerts(self):
        self.copy("2026-10-20_0230", media=False)
        self.copy("2026-10-21_134005", note="Вручную: Сисадминов И.")
        (self.root / "history.log").write_text(
            "21.10.26 13:40\tbackup\terr\t\tСисадминов И.\tнет места на диске\n", encoding="utf-8"
        )
        data = self.client.get("/api/v1/backups/").json()
        self.assertEqual([c["stamp"] for c in data["copies"]], ["2026-10-21_134005", "2026-10-20_0230"])
        self.assertEqual((data["copies"][0]["note"], data["copies"][1]["note"]), ("Вручную: Сисадминов И.", "По расписанию"))
        self.assertEqual((data["copies"][0]["media_size"], data["copies"][1]["media_size"]), (5, None))
        self.assertFalse(data["alive"])
        self.assertTrue(any("не отвечает" in a for a in data["alerts"]))
        self.assertTrue(any("нет места на диске" in a for a in data["alerts"]))

    def test_backup_now_queues_task(self):
        self.assertEqual(self.client.post("/api/v1/backups/").status_code, 409)  # служба не отвечает
        self.beat()
        r = self.client.post("/api/v1/backups/")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(store.tasks(), [{"action": "backup", "stamp": "", "by": "Сисадминов И."}])
        self.assertEqual(self.client.post("/api/v1/backups/").status_code, 409)  # уже в очереди

    def test_restore_needs_word_and_existing_copy(self):
        self.beat()
        self.copy("2026-10-20_0230")
        url = "/api/v1/backups/2026-10-20_0230/restore/"
        self.assertEqual(self.client.post("/api/v1/backups/2026-01-01_0000/restore/", {"confirm": "ВОССТАНОВИТЬ"}).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/backups/..%2Fx/restore/", {"confirm": "ВОССТАНОВИТЬ"}).status_code, 404)
        self.assertEqual(self.client.post(url, {"confirm": "да"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"confirm": "восстановить"}).status_code, 202)
        self.assertEqual(store.tasks()[0]["action"], "restore")
        self.assertEqual(store.tasks()[0]["stamp"], "2026-10-20_0230")

    def test_download(self):
        self.copy("2026-10-20_0230")
        r = self.client.get("/api/v1/backups/2026-10-20_0230/db/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="milarum_db_2026-10-20_0230.dump"', r["Content-Disposition"])
        self.assertEqual(b"".join(r.streaming_content), b"x" * 10)
        self.assertEqual(self.client.get("/api/v1/backups/2026-10-20_0230/other/").status_code, 404)
        with override_settings(BACKUP_ACCEL="/_backups/"):
            r = self.client.get("/api/v1/backups/2026-10-20_0230/media/")
        self.assertEqual(r["X-Accel-Redirect"], "/_backups/media_2026-10-20_0230.tar.gz")

    def test_maintenance_blocks_api_then_migrates(self):
        control = self.root / ".control"
        control.mkdir()
        (control / "maintenance").touch()
        (control / "status").write_text("state=restore\ntext=Восстанавливаю копию 20.10.26 02:30\n", encoding="utf-8")
        r = self.client.get("/api/v1/items/")
        self.assertEqual((r.status_code, r.json()["code"]), (503, "maintenance"))
        public = APIClient().get("/api/v1/maintenance/").json()
        self.assertEqual(public, {"active": True, "text": "Восстанавливаю копию 20.10.26 02:30"})

        (control / "migrate").touch()
        with mock.patch.object(store, "call_command") as migrate:
            r = self.client.get("/api/v1/items/")
        migrate.assert_called_once_with("migrate", interactive=False, verbosity=0)
        self.assertEqual(r.status_code, 200)
        self.assertFalse((control / "maintenance").exists())
        self.assertEqual(APIClient().get("/api/v1/maintenance/").json()["active"], False)

    def test_stale_copy_alert(self):
        self.beat()
        self.copy("2026-01-01_0230")
        os.utime(self.root / ".control" / "heartbeat", (time.time(), time.time()))
        alerts = self.client.get("/api/v1/backups/").json()["alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertIn("больше суток назад", alerts[0])
