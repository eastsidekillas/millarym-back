import secrets
import string

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from app_auth.models import User
from app_auth.rights import USERS
from app_auth.roles import sync_roles


def _password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in p) and any(c.isalpha() for c in p):
            return p


class Command(BaseCommand):
    help = (
        "Завести сотрудников из app_auth/rights.py.USERS. Новым выдаётся случайный пароль — "
        "он печатается ОДИН раз, раздать сотрудникам лично. Существующих не трогает."
    )

    def handle(self, *args, **options):
        sync_roles(reset=False)
        rows = []
        for username, last, first, group_name in USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"last_name": last, "first_name": first, "position": group_name},
            )
            user.groups.add(Group.objects.get(name=group_name))
            if created:
                pwd = _password()
                user.set_password(pwd)
                user.save(update_fields=["password"])
                rows.append(f"  {user.short_name:<18} {username:<15} {pwd}")
            else:
                rows.append(f"  {user.short_name:<18} {username:<15} (уже есть, пароль не менялся)")
        self.stdout.write("Сотрудник          Логин           Пароль")
        self.stdout.write("\n".join(rows))
