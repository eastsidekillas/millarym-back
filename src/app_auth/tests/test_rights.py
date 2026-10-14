from django.core.management import call_command
from django.test import TestCase
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from app_auth.models import User
from app_auth.permissions import HasRight

ACTIONS = ["move_orders_cut", "move_cut_cover", "move_cover_work", "move_work_fg", "ship", "trash",
           "restore", "return_to_work", "move_any", "marks", "edit", "reserve", "fabrics", "catalog"]

#                   or_cu cu_co co_wo wo_fg ship  trash rest  ret   any   marks edit  res   fabr  cat
EXPECTED = {
    "yuldasheva":    [1,    1,    1,    1,    1,    1,    1,    1,    1,    1,    1,    1,    1,    1],
    "zamkova":       [1,    1,    1,    1,    1,    1,    1,    1,    1,    1,    1,    1,    1,    1],
    "kotomtseva":    [1,    1,    0,    0,    0,    0,    1,    0,    0,    1,    1,    1,    1,    0],
    "okisheva":      [0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    1,    1,    0,    0],
    "postnikova":    [0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    1,    1,    0,    0],
    "plokhikh":      [0,    0,    1,    1,    0,    0,    0,    1,    0,    0,    0,    0,    0,    0],
    "voznesenskaya": [0,    0,    0,    0,    1,    1,    1,    0,    0,    0,    0,    0,    0,    0],
}


def _view(code):
    class V(APIView):
        permission_classes = [HasRight(code)]

        def post(self, request):
            return Response({"ok": True})

    return V.as_view()


class RightsMatrixTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_users", stdout=open("/dev/null", "w"))

    def test_seven_users_created(self):
        self.assertEqual(set(User.objects.values_list("username", flat=True)), set(EXPECTED))

    def test_matrix_via_api(self):
        factory = APIRequestFactory()
        for username, row in EXPECTED.items():
            user = User.objects.get(username=username)
            for code, allowed in zip(ACTIONS, row):
                with self.subTest(user=username, action=code):
                    request = factory.post("/x/")
                    force_authenticate(request, user=user)
                    resp = _view(code)(request)
                    self.assertEqual(resp.status_code, 200 if allowed else 403)
                    if not allowed:
                        self.assertIn("Могут:", str(resp.data["detail"]))

    def test_me_lists_rights(self):
        user = User.objects.get(username="plokhikh")
        self.assertEqual(sorted(user.rights), sorted(["move_cover_work", "move_work_fg", "return_to_work"]))

    def test_new_right_is_given_once_and_manual_removal_kept(self):
        from django.contrib.auth.models import Group, Permission

        from app_auth.models import AppliedRight
        from app_auth.roles import sync_roles

        cutting = Group.objects.get(name="Руководитель закройного цеха")
        fabrics = Permission.objects.get(codename="fabrics")
        cutting.permissions.remove(fabrics)
        AppliedRight.objects.filter(code="fabrics").delete()
        sync_roles()
        self.assertTrue(cutting.permissions.filter(codename="fabrics").exists())
        cutting.permissions.remove(fabrics)
        sync_roles()
        self.assertFalse(cutting.permissions.filter(codename="fabrics").exists())

    def test_inactive_user_has_no_rights(self):
        user = User.objects.get(username="yuldasheva")
        user.is_active = False
        user.save()
        self.assertEqual(user.rights, [])
