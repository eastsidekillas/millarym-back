import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import load_workbook
from PIL import Image
from rest_framework.test import APIClient

from app_claims.models import Claim
from app_production import services as s
from app_production.tests.base import Fixtures

MEDIA = tempfile.mkdtemp()


def image():
    buf = BytesIO()
    Image.new("RGB", (800, 600), (120, 30, 30)).save(buf, "JPEG")
    return SimpleUploadedFile("defect.jpg", buf.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA)
class ClaimsTest(Fixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_fixtures()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_create_from_trashed_item_prefills_and_numbers(self):
        [item] = s.create_items(self.manager, model=self.model, fabrics=self.fabrics(), reserve="ИП Петров", extra="левый угол")
        s.trash(self.director, item.pk)
        client = self.client_for(self.manager)
        r = client.post("/api/v1/claims/", {"item": item.pk, "description": "Порван подлокотник", "defect_type": "transport"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertRegex(data["number"], r"^\d{2}/001$")
        self.assertEqual(data["product"], "Бостон, левый угол")
        self.assertEqual(data["item_number"], item.number)
        self.assertEqual(data["counterparty"], "ИП Петров")
        self.assertEqual(data["claim_type"], "review")
        self.assertEqual(data["created_by"]["name"], self.manager.short_name)
        second = client.post("/api/v1/claims/", {"product": "Диван по эскизу", "item_number": "9578/ЗАК"}, format="json").json()
        self.assertTrue(second["number"].endswith("/002"))
        self.assertIsNone(second["item"])

    def test_rights_list_filters_and_stats(self):
        self.assertEqual(self.client_for(self.storekeeper).post("/api/v1/claims/", {"product": "x"}, format="json").status_code, 403)
        client = self.client_for(self.manager)
        for defect, who in [("transport", "ООО Агат"), ("transport", "ИП Петров"), ("material", "ООО Агат")]:
            client.post("/api/v1/claims/", {"product": "Бали", "counterparty": who, "defect_type": defect}, format="json")
        reader = self.client_for(self.storekeeper)
        self.assertEqual(reader.get("/api/v1/claims/?defect_type=transport").json()["count"], 2)
        self.assertEqual(reader.get("/api/v1/claims/?q=Агат").json()["count"], 2)
        st = reader.get("/api/v1/claims/stats/?q=Агат").json()
        defects = {d["id"]: d["count"] for d in st["defect_type"]}
        self.assertEqual((st["total"], defects["transport"], defects["material"]), (2, 1, 1))
        self.assertIn("Транспортировка", [c["name"] for c in reader.get("/api/v1/claims/choices/").json()["defect_type"]])

    def test_edit_photos_and_pdf(self):
        client = self.client_for(self.manager)
        claim = client.post("/api/v1/claims/", {"product": "Бали", "act_date": "2026-10-10"}, format="json").json()
        r = client.patch(f"/api/v1/claims/{claim['id']}/", {"research": "Шов разошёлся", "claim_type": "repair"}, format="json")
        self.assertEqual(r.json()["claim_type_label"], "Ремонт")
        photo = client.post(f"/api/v1/claims/{claim['id']}/photos/", {"photo": image()}, format="multipart")
        self.assertEqual(photo.status_code, 201, photo.content)
        self.assertTrue(photo.json()["photo"].endswith(".webp"))
        self.assertEqual(len(client.get(f"/api/v1/claims/{claim['id']}/").json()["photos"]), 1)
        pdf = client.get(f"/api/v1/claims/{claim['id']}/pdf/")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        blank = client.get("/api/v1/claims/blank/")
        sheet = load_workbook(BytesIO(blank.content)).active
        self.assertEqual(sheet["A6"].value, "АКТ-ПРЕТЕНЗИЯ")
        self.assertEqual(sheet["A13"].value, "Описание претензии")
        self.assertIn("ИП Окулова В.А.", sheet.data_validations.dataValidation[0].formula1)
        self.assertEqual(client.delete(f"/api/v1/claims/{claim['id']}/photos/{photo.json()['id']}/").status_code, 204)
        self.assertEqual(client.delete(f"/api/v1/claims/{claim['id']}/").status_code, 405)
        self.assertEqual(Claim.objects.count(), 1)

    def test_report_by_defect_type(self):
        client = self.client_for(self.manager)
        for defect in ("transport", "transport", "material", ""):
            client.post("/api/v1/claims/", {"product": "Бали", "defect_type": defect}, format="json")
        from django.utils import timezone

        today = timezone.localdate().isoformat()
        data = client.get(f"/api/v1/reports/claims/?from={today}&to={today}").json()
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["rows"][0]["group"], "Транспортировка: 2 шт.")
        self.assertEqual(data["rows"][-1]["group"], "Не указан: 1 шт.")
        self.assertEqual(client.get(f"/api/v1/reports/claims/xlsx/?from={today}&to={today}").status_code, 200)

    def test_close_and_reopen(self):
        client = self.client_for(self.manager)
        a = client.post("/api/v1/claims/", {"product": "Бали", "defect_type": "transport"}, format="json").json()
        b = client.post("/api/v1/claims/", {"product": "Канзас"}, format="json").json()
        self.assertEqual(a["state"], "open")
        self.assertEqual(self.client_for(self.storekeeper).post(f"/api/v1/claims/{a['id']}/close/", {"state": "done"}, format="json").status_code, 403)
        self.assertEqual(client.post(f"/api/v1/claims/{a['id']}/close/", {"state": "open"}, format="json").status_code, 400)
        done = client.post(f"/api/v1/claims/{a['id']}/close/", {"state": "done", "note": " Заменили подлокотник "}, format="json").json()
        self.assertEqual((done["state"], done["state_label"], done["close_note"]), ("done", "Выполнена", "Заменили подлокотник"))
        self.assertEqual(done["closed_by"]["name"], self.manager.short_name)
        client.post(f"/api/v1/claims/{b['id']}/close/", {"state": "withdrawn"}, format="json")
        self.assertEqual(client.patch(f"/api/v1/claims/{a['id']}/", {"state": "open"}, format="json").json()["state"], "done")

        self.assertEqual(client.get("/api/v1/claims/?state=open").json()["count"], 0)
        self.assertEqual(client.get("/api/v1/claims/?state=closed").json()["count"], 2)
        self.assertEqual(client.get("/api/v1/claims/?state=withdrawn").json()["results"][0]["state_label"], "Снята покупателем")
        states = {x["id"]: x["count"] for x in client.get("/api/v1/claims/stats/?state=open").json()["state"]}
        self.assertEqual(states, {"open": 0, "done": 1, "withdrawn": 1})
        self.assertTrue(client.get(f"/api/v1/claims/{a['id']}/pdf/").content.startswith(b"%PDF"))

        reopened = client.post(f"/api/v1/claims/{a['id']}/reopen/").json()
        self.assertEqual((reopened["state"], reopened["closed_at"], reopened["closed_by"]), ("open", None, None))
        self.assertEqual(reopened["close_note"], "Заменили подлокотник")
