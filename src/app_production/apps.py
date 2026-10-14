from django.apps import AppConfig


class AppProductionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_production"
    verbose_name = "Производство"
