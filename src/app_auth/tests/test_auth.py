from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from app_auth.models import User

ACCESS = settings.SIMPLE_JWT["COOKIE_SETTINGS"]["ACCESS_TOKEN"]["key"]
REFRESH = settings.SIMPLE_JWT["COOKIE_SETTINGS"]["REFRESH_TOKEN"]["key"]


class AuthFlowTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="postnikova", password="Proba-2026", last_name="Постникова", first_name="О.",
            email="Postnikova@Milarum.ru", position="Менеджер",
        )

    def login(self, login, password="Proba-2026"):
        return self.client.post("/api/v1/users/login/", {"login": login, "password": password}, format="json")

    def test_closed_without_login(self):
        self.assertEqual(self.client.get("/api/v1/users/me/").status_code, 401)

    def test_login_by_username_sets_httponly_cookies(self):
        r = self.login("postnikova")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["short_name"], "Постникова О.")
        self.assertTrue(r.cookies[ACCESS]["httponly"])
        self.assertTrue(r.cookies[REFRESH]["httponly"])
        self.assertEqual(r.cookies[REFRESH]["path"], "/api/v1/token/refresh/")
        self.assertEqual(self.client.get("/api/v1/users/me/").data["username"], "postnikova")

    def test_login_case_insensitive_and_by_email(self):
        self.assertEqual(self.login("POSTNIKOVA").status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.login("postnikova@milarum.ru").status_code, 200)

    def test_wrong_password(self):
        r = self.login("postnikova", "nope")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.data["detail"], "Неверный логин или пароль.")

    def test_unknown_login_same_message(self):
        self.assertEqual(self.login("nobody", "x").data["detail"], "Неверный логин или пароль.")

    def test_inactive_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.login("postnikova").status_code, 401)

    def test_refresh_and_logout(self):
        self.login("postnikova")
        self.client.cookies.pop(ACCESS)
        self.assertEqual(self.client.get("/api/v1/users/me/").status_code, 401)
        self.assertEqual(self.client.post("/api/v1/token/refresh/").status_code, 204)
        self.assertEqual(self.client.get("/api/v1/users/me/").status_code, 200)
        r = self.client.post("/api/v1/users/logout/")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.cookies[ACCESS].value, "")
        self.assertEqual(self.client.get("/api/v1/users/me/").status_code, 401)

    def test_bad_access_token_is_401(self):
        self.client.cookies[ACCESS] = "garbage"
        self.assertEqual(self.client.get("/api/v1/users/me/").status_code, 401)

    def test_password_change(self):
        self.login("postnikova")
        r = self.client.post("/api/v1/users/password/", {"old_password": "wrong", "new_password": "Novy-parol-77"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("old_password", r.data["errors"])
        r = self.client.post("/api/v1/users/password/", {"old_password": "Proba-2026", "new_password": "123"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/users/password/", {"old_password": "Proba-2026", "new_password": "Novy-parol-77"}, format="json")
        self.assertEqual(r.status_code, 204)
        self.client.cookies.clear()
        self.assertEqual(self.login("postnikova", "Novy-parol-77").status_code, 200)

    def test_no_lockout_when_disabled(self):
        """По умолчанию (только локальная сеть) блокировки нет."""
        for _ in range(8):
            self.assertEqual(self.login("postnikova", "bad").status_code, 401)
        self.assertEqual(self.login("postnikova").status_code, 200)

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=5)
    def test_lockout_after_five_failures_any_spelling(self):
        spellings = ["postnikova", "Postnikova", "postnikova@milarum.ru", "POSTNIKOVA"]
        for login in spellings:
            self.assertEqual(self.login(login, "bad").status_code, 401)
        r = self.login("postnikova", "bad")  # 5-я неудача — блокировка
        self.assertEqual(r.status_code, 429)
        r = self.login("postnikova")  # верный пароль, но уже заблокировано
        self.assertEqual(r.status_code, 429)
        self.assertIn("заблокирован", r.json()["detail"])

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=5)
    def test_success_resets_failures(self):
        for _ in range(4):
            self.login("postnikova", "bad")
        self.assertEqual(self.login("postnikova").status_code, 200)
        for _ in range(4):
            self.login("postnikova", "bad")
        self.assertEqual(self.login("postnikova").status_code, 200)

    def test_email_unique_case_insensitive(self):
        from django.core.exceptions import ValidationError

        other = User(username="okisheva", email="POSTNIKOVA@milarum.ru")
        other.set_password("x")
        with self.assertRaises(ValidationError):
            other.full_clean()
