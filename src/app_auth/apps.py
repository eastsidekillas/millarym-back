from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _create_roles(sender, **kwargs):
    from .roles import sync_roles

    sync_roles(reset=False)


class AppAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_auth"
    verbose_name = "Сотрудники и права"

    def ready(self):
        # post_migrate: к этому моменту django уже создал Permission из Meta.permissions
        post_migrate.connect(_create_roles, sender=self)
