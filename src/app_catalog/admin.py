from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Deadlines, Fabric, KitOption, ProductModel, Team


@admin.display(description="фото")
def thumb(obj):
    if not obj.photo_thumb:
        return "—"
    return format_html('<img src="{}" style="height:48px;border-radius:6px">', obj.photo_thumb.url)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "sort", "active"]
    list_editable = ["sort", "active"]


@admin.register(ProductModel)
class ProductModelAdmin(admin.ModelAdmin):
    list_display = [thumb, "name", "category", "active"]
    list_display_links = [thumb, "name"]
    list_filter = ["category", "active"]
    list_editable = ["active"]
    search_fields = ["name"]


@admin.register(Fabric)
class FabricAdmin(admin.ModelAdmin):
    list_display = [thumb, "name", "active", "created_at"]
    list_display_links = [thumb, "name"]
    list_filter = ["active"]
    list_editable = ["active"]
    search_fields = ["name"]


@admin.register(KitOption)
class KitOptionAdmin(admin.ModelAdmin):
    list_display = ["name", "sort", "active"]
    list_editable = ["sort", "active"]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "foreman", "sort", "active"]
    list_editable = ["sort", "active"]
    search_fields = ["name", "foreman"]


@admin.register(Deadlines)
class DeadlinesAdmin(admin.ModelAdmin):
    list_display = ["__str__", "fabric_days", "cut_days", "output_days", "trash_days"]

    def has_add_permission(self, request):
        return not Deadlines.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
