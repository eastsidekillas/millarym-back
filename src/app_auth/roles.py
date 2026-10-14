from django.contrib.auth.models import Group, Permission

from .rights import ROLES


def sync_roles(reset: bool = False) -> list[str]:
    """
    Создаёт группы и права по таблице rights.ROLES.
    reset=False: существующую группу не трогаем (права могли поменять в админке).
    reset=True: приводим права всех групп к таблице.
    Возвращает список созданных/обновлённых групп.
    """
    touched = []
    perms = {p.codename: p for p in Permission.objects.filter(content_type__app_label="app_auth")}
    for name, codes in ROLES.items():
        group, created = Group.objects.get_or_create(name=name)
        if created or reset:
            group.permissions.set([perms[c] for c in codes if c in perms])
            touched.append(name)
    return touched
