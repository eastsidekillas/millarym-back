import shutil
import tempfile
import zipfile
from io import BytesIO, StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from PIL import Image

from app_catalog.models import Fabric

MEDIA = tempfile.mkdtemp()


def png(color="red") -> bytes:
    buf = BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=MEDIA)
class ImportFabricsTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def run_cmd(self, *args, **kwargs):
        out = StringIO()
        call_command("import_fabrics", *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_folder(self):
        Fabric.objects.create(name="Velutto 03")
        (self.dir / "sub").mkdir()
        (self.dir / "velutto  03.jpg").write_bytes(png())
        (self.dir / "sub" / "Arben_ultra_grafit.png").write_bytes(png("gray"))
        (self.dir / "Arben ultra grafit.jpeg").write_bytes(png())
        (self.dir / "broken.jpg").write_bytes(b"not an image")
        (self.dir / "notes.txt").write_text("x")

        out = self.run_cmd(str(self.dir), dry_run=True)
        self.assertIn("Фото поставлено: 2, из них новых тканей: 1", out)
        self.assertEqual(Fabric.objects.count(), 1)

        out = self.run_cmd(str(self.dir))
        self.assertIn("Картинок: 4. Фото поставлено: 2, из них новых тканей: 1", out)
        self.assertIn("уже встречалась", out)
        self.assertIn("broken.jpg: не картинка", out)
        self.assertEqual(Fabric.objects.count(), 2)
        self.assertTrue(all(f.photo and f.photo_thumb for f in Fabric.objects.all()))

        out = self.run_cmd(str(self.dir))
        self.assertIn("Фото поставлено: 0", out)
        self.assertIn("Фото уже было (без --replace не трогаем): 2", out)
        self.assertIn("Фото поставлено: 2", self.run_cmd(str(self.dir), replace=True))

    def test_zip_and_no_create(self):
        Fabric.objects.create(name="Барон 11")
        path = self.dir / "fabrics.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("ткани/Барон 11.jpg", png())
            archive.writestr("ткани/Новая ткань.jpg", png())
            archive.writestr("__MACOSX/ткани/._Барон 11.jpg", b"junk")
        out = self.run_cmd(str(path), no_create=True)
        self.assertIn("Фото поставлено: 1", out)
        self.assertIn("Без ткани в справочнике пропущено: 1", out)
        self.assertTrue(Fabric.objects.get(name="Барон 11").photo)
        self.assertFalse(Fabric.objects.filter(name="Новая ткань").exists())

    def test_bad_path(self):
        with self.assertRaises(CommandError):
            self.run_cmd(str(self.dir / "nope"))
        with self.assertRaises(CommandError):
            self.run_cmd(str(self.dir))
