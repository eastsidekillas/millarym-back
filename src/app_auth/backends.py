from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from .models import User


def find_user(login: str) -> User | None:
    """Ищет сотрудника по логину или почте без учёта регистра."""
    login = (login or "").strip()
    if not login:
        return None
    q = Q(username__iexact=login)
    if "@" in login:
        q |= Q(email__iexact=login)
    return User.objects.filter(q).order_by("id").first()


class LoginOrEmailBackend(ModelBackend):
    """Вход по логину или почте (spec 08 §2.0)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        user = find_user(username or kwargs.get("login") or "")
        if user is None:
            # тратим время как при реальной проверке — не выдаём, есть ли такой логин
            User().set_password(password or "")
            return None
        if user.check_password(password or "") and self.user_can_authenticate(user):
            return user
        return None
