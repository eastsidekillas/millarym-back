from functools import lru_cache

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .rights import RIGHTS


def who_can(code: str) -> str:
    from .models import User

    names = [u.short_name for u in User.objects.filter(is_active=True) if u.has_perm(f"app_auth.{code}")]
    return ", ".join(names) or "никто"


def no_right_message(code: str) -> str:
    return f"Нет прав: {RIGHTS[code].lower()}. Могут: {who_can(code)}."


@lru_cache(maxsize=None)
def HasRight(code: str) -> type[BasePermission]:
    if code not in RIGHTS:
        raise ValueError(f"Неизвестное право: {code}")

    class _HasRight(BasePermission):
        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            if user.has_perm(f"app_auth.{code}"):
                return True
            self.message = no_right_message(code)
            return False

    _HasRight.__name__ = f"HasRight_{code}"
    return _HasRight


@lru_cache(maxsize=None)
def ReadOrRight(code: str) -> type[BasePermission]:
    write = HasRight(code)

    class _ReadOrRight(BasePermission):
        def has_permission(self, request, view):
            if request.method in SAFE_METHODS:
                return bool(request.user and request.user.is_authenticated)
            check = write()
            if check.has_permission(request, view):
                return True
            self.message = getattr(check, "message", None)
            return False

    _ReadOrRight.__name__ = f"ReadOrRight_{code}"
    return _ReadOrRight
