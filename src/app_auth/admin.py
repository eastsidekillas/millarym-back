from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "last_name", "first_name", "position", "email", "is_active", "last_login")
    list_filter = ("groups", "is_active", "is_staff")
    search_fields = ("username", "last_name", "first_name", "email")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Сотрудник", {"fields": ("last_name", "first_name", "position", "email")}),
        ("Роль и права", {"fields": ("is_active", "groups", "user_permissions", "is_staff", "is_superuser")}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "last_name", "first_name", "position", "email",
                                                  "groups", "password1", "password2")}),
    )
