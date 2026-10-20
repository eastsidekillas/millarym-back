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
        self.assertTrue(fabric.active)
        self.assertTrue(r.json()["photo"].startswith("/media/fabrics/"))
        self.assertTrue(r.json()["photo"].endswith(".webp"))
        self.assertTrue(r.json()["photo_thumb"].startswith("/media/fabrics/thumbs/"))
        with Image.open(fabric.photo.path) as full, Image.open(fabric.photo_thumb.path) as thumb:
            self.assertEqual(full.size, (1600, 1067))
            self.assertLessEqual(max(thumb.size), 300)
            self.assertEqual(full.format, "WEBP")
            self.assertEqual(thumb.format, "WEBP")

    def test_multipart_edit_keeps_active(self):
        fabric = Fabric.objects.create(name="Рогожка")
        client = self.as_user("kotomtseva")
        client.patch(f"/api/v1/fabrics/{fabric.pk}/", {"photo": image()}, format="multipart")
        fabric.refresh_from_db()
        self.assertTrue(fabric.active)
        client.patch(f"/api/v1/fabrics/{fabric.pk}/", {"active": "false"}, format="multipart")
        fabric.refresh_from_db()
        self.assertFalse(fabric.active)

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

    def test_fabric_in_work_count(self):
        from app_production import services
        from app_auth.models import User

        velour = Fabric.objects.create(name="Велюр")
        other = Fabric.objects.create(name="Рогожка")
        sofas = Category.objects.get(name="Прямые диваны")
        model = ProductModel.objects.create(name="Бостон", category=sofas)
        manager = User.objects.get(username="okisheva")
        items = services.create_items(manager, model=model, qty=3, fabrics=[{"slot": "main", "fabric": velour}, {"slot": "comp1", "fabric": velour}])
        services.trash(User.objects.get(username="voznesenskaya"), items[0].pk)
        rows = {f["name"]: f["in_work"] for f in self.as_user("okisheva").get("/api/v1/fabrics/?ordering=-in_work").json()["results"]}
        self.assertEqual(rows, {"Велюр": 2, "Рогожка": 0})
        self.assertEqual(other.pk, Fabric.objects.get(name="Рогожка").pk)

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

    def test_hide(self):
        fabric = Fabric.objects.create(name="Т")
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

    def test_counts_for_refs_screen(self):
        from app_production import services

        sofas = Category.objects.get(name="Прямые диваны")
        boston = ProductModel.objects.create(name="Бостон", category=sofas)
        ProductModel.objects.create(name="Старый", category=sofas, active=False)
        fabric = Fabric.objects.create(name="Велюр")
        items = services.create_items(
            User.objects.get(username="okisheva"), model=boston, qty=2, fabrics=[{"slot": "main", "fabric": fabric}]
        )
        services.trash(User.objects.get(username="voznesenskaya"), items[0].pk)
        client = self.as_user("okisheva")
        models = {m["name"]: m["in_work"] for m in client.get("/api/v1/models/").json()}
        self.assertEqual(models, {"Бостон": 1, "Старый": 0})
        names = [m["name"] for m in client.get("/api/v1/models/").json()]
        self.assertEqual(names, sorted(names))
        listed = client.get("/api/v1/categories/").json()
        self.assertEqual([c["sort"] for c in listed], sorted(c["sort"] for c in listed))
        cats = {c["name"]: c["models_count"] for c in listed}
        self.assertEqual(cats["Прямые диваны"], 1)
        created = self.as_user("zamkova").post("/api/v1/models/", {"name": "Новая", "category": sofas.pk}, format="json")
        self.assertEqual(created.json()["in_work"], 0)

    def test_deadlines_limits(self):
        client = self.as_user("yuldasheva")
        self.assertEqual(client.patch("/api/v1/deadlines/", {"trash_days": 0}, format="json").status_code, 400)
        self.assertEqual(client.patch("/api/v1/deadlines/", {"trash_days": 400}, format="json").status_code, 400)

    def test_delete_only_unused(self):
        from app_catalog.models import KitOption, Team
        from app_production import services as s

        manager = User.objects.get(username="okisheva")
        director = self.as_user("yuldasheva")
        sofas = Category.objects.get(name="Прямые диваны")
        used_model = ProductModel.objects.create(name="Бостон", category=sofas)
        spare_model = ProductModel.objects.create(name="Опечатка", category=sofas)
        r = self.as_user("kotomtseva").post("/api/v1/fabrics/", {"name": "Лишняя", "photo": image()}, format="multipart")
        spare_fabric = Fabric.objects.get(pk=r.json()["id"])
        used_fabric = Fabric.objects.create(name="Велюр")
        team = Team.objects.create(name="Бригада 1")
        [item] = s.create_items(manager, model=used_model, fabrics=[{"slot": "main", "fabric": used_fabric}])
        s.trash(User.objects.get(username="yuldasheva"), item.pk)

        models = {m["name"]: m for m in director.get("/api/v1/models/").json()}
        self.assertEqual((models["Бостон"]["used"], models["Опечатка"]["used"]), (1, 0))
        r = director.delete(f"/api/v1/models/{used_model.pk}/")
        self.assertEqual(r.status_code, 409)
        self.assertIn("Есть в 1 изд.", r.json()["detail"])
        self.assertEqual(director.delete(f"/api/v1/models/{spare_model.pk}/").status_code, 204)
        self.assertFalse(ProductModel.objects.filter(pk=spare_model.pk).exists())

        self.assertEqual(self.as_user("okisheva").delete(f"/api/v1/fabrics/{spare_fabric.pk}/").status_code, 403)
        self.assertEqual(self.as_user("kotomtseva").delete(f"/api/v1/fabrics/{used_fabric.pk}/").status_code, 409)
        storage, paths = spare_fabric.photo.storage, (spare_fabric.photo.name, spare_fabric.photo_thumb.name)
        self.assertEqual(self.as_user("kotomtseva").delete(f"/api/v1/fabrics/{spare_fabric.pk}/").status_code, 204)
        self.assertFalse(any(storage.exists(p) for p in paths))

        self.assertEqual(director.delete(f"/api/v1/categories/{sofas.pk}/").status_code, 409)
        empty = Category.objects.create(name="Пустая")
        self.assertEqual(director.delete(f"/api/v1/categories/{empty.pk}/").status_code, 204)
        self.assertEqual(director.delete(f"/api/v1/teams/{team.pk}/").status_code, 204)
        kit = KitOption.objects.create(name="Опечатка")
        self.assertEqual(director.delete(f"/api/v1/kit-options/{kit.pk}/").status_code, 204)
