from django.http import JsonResponse

from .backends import find_user


def username_for_lockout(request, credentials) -> str:
    """
    Ключ блокировки — логин сотрудника: «Postnikova», «postnikova» и её почта
    считаются вместе, иначе можно обходить лимит, меняя написание.
    """
    raw = ((credentials or {}).get("username") or "").strip()
    user = find_user(raw)
    return (user.username if user else raw).lower()


def lockout_response(request, *args, **kwargs):
    from django.conf import settings

    minutes = int(settings.AXES_COOLOFF_TIME.total_seconds() // 60)
    return JsonResponse(
        {"detail": f"Слишком много неверных паролей. Вход заблокирован на {minutes} минут. "
                   f"Снять блокировку может директор или администратор."},
        status=429,
    )
