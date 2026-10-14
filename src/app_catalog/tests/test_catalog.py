import shutil
import tempfile
from io import BytesIO
from unittest import skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from app_auth.models import User
from app_catalog.models import Category, Fabric, ProductModel

MEDIA = tempfile.mkdtemp()


def image(name="t.jpg", size=(3000, 2000), mode="RGB", fmt="JPEG"):
    buf = BytesIO()
    Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{fmt.lower()}")


@override_settings(MEDIA_ROOT=MEDIA)
class CatalogApiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_users", stdout=open("/dev/null", "w"))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def as_user(self, username):
        client = APIClient()
        client.force_authenticate(User.objects.get(username=username))
        return client

    def test_closed_without_login(self):
        self.assertEqual(APIClient().get("/api/v1/fabrics/").status_code, 401)

    def test_seeded_dictionaries(self):
        client = self.as_user("plokhikh")
        names = [c["name"] for c in client.get("/api/v1/categories/").json()]
        self.assertIn("Кровати", names)
        self.assertEqual(len(names), 7)
        kit = [k["name"] for k in client.get("/api/v1/kit-options/").json()]
        self.assertEqual(kit[:2], ["Левый угол", "Правый угол"])
        self.assertEqual(
            client.get("/api/v1/deadlines/").json(),
            {"fabric_days": 10, "cut_days": 20, "output_days": 30, "trash_days": 30},
        )

    def test_fabric_upload_shrinks_photo(self):
        r = self.as_user("kotomtseva").post(
            "/api/v1/fabrics/", {"name": "Велюр Блэк 03", "photo": image()}, format="multipart"
        )
        self.assertEqual(r.status_code, 201, r.content)
        fabric = Fabric.objects.get()
        self.assertTrue(r.json()["photo"].startswith("/media/fabrics/"))
        self.assertTrue(r.json()["photo_thumb"].startswith("/media/fabrics/thumbs/"))
        with Image.open(fabric.photo.path) as full, Image.open(fabric.photo_thumb.path) as thumb:
            self.assertEqual(full.size, (1600, 1067))
            self.assertLessEqual(max(thumb.size), 300)
            self.assertEqual(full.format, "JPEG")

    def test_png_with_transparency(self):
        r = self.as_user("yuldasheva").post(
            "/api/v1/fabrics/",
            {"name": "Рогожка", "photo": image("p.png", (400, 400), "RGBA", "PNG")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_not_an_image(self):
        bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        r = self.as_user("kotomtseva").post("/api/v1/fabrics/", {"name": "X", "photo": bad}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("photo", r.json()["errors"])

    def test_replace_and_remove_photo_deletes_files(self):
        client = self.as_user("kotomtseva")
        fid = client.post("/api/v1/fabrics/", {"name": "Шенилл", "photo": image()}, format="multipart").json()["id"]
        fabric = Fabric.objects.get(pk=fid)
        storage, first = fabric.photo.storage, (fabric.photo.name, fabric.photo_thumb.name)
        client.patch(f"/api/v1/fabrics/{fid}/", {"photo": image()}, format="multipart")
        self.assertFalse(any(storage.exists(p) for p in first))
        fabric.refresh_from_db()
        second = (fabric.photo.name, fabric.photo_thumb.name)
        r = client.patch(f"/api/v1/fabrics/{fid}/", {"photo": None}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["photo"])
        self.assertFalse(any(storage.exists(p) for p in second))

    def test_fabric_rights(self):
        for username in ("okisheva", "plokhikh", "voznesenskaya"):
            r = self.as_user(username).post("/api/v1/fabrics/", {"name": "Т"}, format="json")
            self.assertEqual(r.status_code, 403)
            self.assertIn("Котомцева С.", r.json()["detail"])

    @skipUnless(connection.vendor == "postgresql", "SQLite не сравнивает кириллицу без учёта регистра")
    def test_fabric_name_unique_ignoring_case(self):
        client = self.as_user("kotomtseva")
        self.assertEqual(client.post("/api/v1/fabrics/", {"name": "Велюр"}, format="json").status_code, 201)
        r = client.post("/api/v1/fabrics/", {"name": " ВЕЛЮР "}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("name", r.json()["errors"])

    def test_fabrics_paginated_and_searchable(self):
        Fabric.objects.bulk_create([Fabric(name=f"Ткань {i:03}") for i in range(60)])
        Fabric.objects.create(name="Экокожа белая", active=False)
        client = self.as_user("okisheva")
        page = client.get("/api/v1/fabrics/").json()
        self.assertEqual(page["count"], 61)
        self.assertEqual(len(page["results"]), 50)
        found = client.get("/api/v1/fabrics/?search=Экокожа").json()["results"]
        self.assertEqual([f["name"] for f in found], ["Экокожа белая"])
        self.assertEqual(client.get("/api/v1/fabrics/?active=false").json()["count"], 1)

    def test_fabric_name_unique(self):
        client = self.as_user("kotomtseva")
        client.post("/api/v1/fabrics/", {"name": "Velvet"}, format="json")
        r = client.post("/api/v1/fabrics/", {"name": " velvet "}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_models_need_catalog_right(self):
        sofas = Category.objects.get(name="Прямые диваны")
        body = {"name": "Бостон", "category": sofas.pk}
        self.assertEqual(self.as_user("kotomtseva").post("/api/v1/models/", body, format="json").status_code, 403)
        r = self.as_user("zamkova").post("/api/v1/models/", body, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["category_name"], "Прямые диваны")

    def test_models_filter_by_category(self):
        beds, chairs = Category.objects.get(name="Кровати"), Category.objects.get(name="Кресла")
        ProductModel.objects.create(name="Кровать Ницца", category=beds)
        ProductModel.objects.create(name="Дубай кресло", category=chairs)
        r = self.as_user("postnikova").get(f"/api/v1/models/?category={beds.pk}").json()
        self.assertEqual([m["name"] for m in r], ["Кровать Ницца"])

    def test_no_delete(self):
        fabric = Fabric.objects.create(name="Т")
        r = self.as_user("yuldasheva").delete(f"/api/v1/fabrics/{fabric.pk}/")
        self.assertEqual(r.status_code, 405)
        r = self.as_user("yuldasheva").patch(f"/api/v1/fabrics/{fabric.pk}/", {"active": False}, format="json")
        self.assertFalse(r.json()["active"])

    def test_deadlines_edit(self):
        self.assertEqual(self.as_user("okisheva").patch("/api/v1/deadlines/", {"cut_days": 25}).status_code, 403)
        r = self.as_user("yuldasheva").patch("/api/v1/deadlines/", {"cut_days": 25}, format="json")
        self.assertEqual(r.json()["cut_days"], 25)

    def test_teams(self):
        client = self.as_user("yuldasheva")
        r = client.post("/api/v1/teams/", {"name": "Бригада 1", "foreman": "Иванов"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.as_user("plokhikh").post("/api/v1/teams/", {"name": "Б2"}).status_code, 403)
