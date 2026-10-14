from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .rights import RIGHTS


class User(AbstractUser):
    email = models.EmailField("почта", blank=True, default="")
    position = models.CharField("должность", max_length=120, blank=True, default="")

    class Meta:
        verbose_name = "сотрудник"
        verbose_name_plural = "сотрудники"
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="user_email_unique_ci",
                violation_error_message="Эта почта уже указана у другого сотрудника.",
            ),
        ]

    @property
    def short_name(self) -> str:
        first = self.first_name.strip()
        initial = first if first.endswith(".") and len(first) <= 3 else (first[:1] + "." if first else "")
        return f"{self.last_name} {initial}".strip() or self.username

    @property
    def role_name(self) -> str:
        return self.position or ", ".join(self.groups.values_list("name", flat=True))

    @property
    def rights(self) -> list[str]:
        if not self.is_active:
            return []
        return [code for code in RIGHTS if self.has_perm(f"app_auth.{code}")]

    def __str__(self) -> str:
        return self.short_name


class AccessRights(models.Model):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = list(RIGHTS.items())
        verbose_name = "права CRM"
        verbose_name_plural = "права CRM"


class AppliedRight(models.Model):
    code = models.CharField(max_length=64, unique=True)
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "выданное право"
        verbose_name_plural = "выданные права"
