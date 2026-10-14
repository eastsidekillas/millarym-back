from django.contrib.auth.models import Group, Permission

from .models import AppliedRight
from .rights import RIGHTS, ROLES


def sync_roles(reset: bool = False) -> list[str]:
    """Новые группы и новые коды прав раздаются по ROLES один раз; ручные правки в админке сохраняются."""
    perms = {p.codename: p for p in Permission.objects.filter(content_type__app_label="app_auth")}
    applied = set(AppliedRight.objects.values_list("code", flat=True))
    touched = []
    for name, codes in ROLES.items():
        group, created = Group.objects.get_or_create(name=name)
        if created or reset:
            group.permissions.set([perms[c] for c in codes if c in perms])
            touched.append(name)
            continue
        new = [perms[c] for c in codes if c in perms and c not in applied]
        if new:
            group.permissions.add(*new)
            touched.append(name)
    AppliedRight.objects.bulk_create(
        [AppliedRight(code=c) for c in RIGHTS if c in perms and c not in applied],
        ignore_conflicts=True,
    )
    return touched
