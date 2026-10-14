from functools import lru_cache

from rest_framework.permissions import BasePermission

from .rights import RIGHTS


def who_can(code: str) -> str:
    from .models import User

    names = [u.short_name for u in User.objects.filter(is_active=True) if u.has_perm(f"app_auth.{code}")]
    return ", ".join(names) or "никто"


@lru_cache(maxsize=None)
def HasRight(code: str) -> type[BasePermission]:
    """
    Класс прав DRF для действия из rights.RIGHTS:
        permission_classes = [HasRight("move_orders_cut")]
    Без права — 403 «Нет прав. Могут: …» (spec 08 §12а).
    """
    if code not in RIGHTS:
        raise ValueError(f"Неизвестное право: {code}")

    class _HasRight(BasePermission):
        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            if user.has_perm(f"app_auth.{code}"):
                return True
            self.message = f"Нет прав: {RIGHTS[code].lower()}. Могут: {who_can(code)}."
            return False

    _HasRight.__name__ = f"HasRight_{code}"
    return _HasRight
