from django.contrib import admin

from .models import Item, ItemEvent, ItemFabric, NumberSequence


@admin.register(NumberSequence)
class NumberSequenceAdmin(admin.ModelAdmin):
    list_display = ["period", "last_value"]


class ItemFabricInline(admin.TabularInline):
    model = ItemFabric
    extra = 0
    can_delete = False
    readonly_fields = ["slot", "fabric", "meters"]

    def has_add_permission(self, request, obj=None):
        return False


class ItemEventInline(admin.TabularInline):
    model = ItemEvent
    extra = 0
    can_delete = False
    readonly_fields = ["at", "user", "kind", "text"]
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ["number", "model", "extra", "reserve", "stage", "indiv", "trashed_at", "stage_since"]
    list_filter = ["stage", "indiv", "trash_reason", "model__category"]
    search_fields = ["number", "legacy_number", "reserve", "model__name", "extra"]
    inlines = [ItemFabricInline, ItemEventInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ItemEvent)
class ItemEventAdmin(admin.ModelAdmin):
    list_display = ["at", "user", "item", "kind", "text"]
    list_filter = ["kind", "user"]
    search_fields = ["item__number", "text"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
