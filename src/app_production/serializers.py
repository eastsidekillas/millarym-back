from datetime import timedelta

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from app_catalog.images import jpeg_url
from app_catalog.models import Fabric, ProductModel, Team

from .actions import available_actions
from .models import AmountUnit, FabricSlot, Item, ItemEvent, ItemFabric, Stage
from .services import MAX_QTY


class RefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class FabricRefSerializer(RefSerializer):
    photo_thumb = serializers.CharField(allow_null=True)
    photo = serializers.CharField(allow_null=True)
    photo_jpeg = serializers.CharField(allow_null=True)


class ItemRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()


class ActionSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    allowed = serializers.BooleanField()
    reason = serializers.CharField()
    to = serializers.CharField(required=False)
    needs_team = serializers.BooleanField(required=False)


class ItemFabricSerializer(serializers.ModelSerializer):
    slot_label = serializers.CharField(source="get_slot_display")
    fabric = serializers.SerializerMethodField()

    class Meta:
        model = ItemFabric
        fields = ["slot", "slot_label", "fabric", "meters", "unit"]

    @extend_schema_field(FabricRefSerializer)
    def get_fabric(self, obj):
        fabric = obj.fabric
        return {
            "id": fabric.id,
            "name": fabric.name,
            "photo_thumb": fabric.photo_thumb.url if fabric.photo_thumb else None,
            "photo": fabric.photo.url if fabric.photo else None,
            "photo_jpeg": jpeg_url("fabrics", fabric),
        }


class ItemSerializer(serializers.ModelSerializer):
    model = RefSerializer(allow_null=True)
    title = serializers.CharField(read_only=True)
    team = RefSerializer(allow_null=True)
    stage_label = serializers.CharField(source="get_stage_display")
    trash_reason_label = serializers.CharField(source="get_trash_reason_display")
    manager = serializers.CharField(source="manager.short_name")
    fabrics = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()
    is_free = serializers.BooleanField()
    purge_at = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            "id", "number", "legacy_number", "model", "custom_name", "title", "extra", "comment", "table_no",
            "reserve", "reserved_at", "is_free",
            "stage", "stage_label", "stage_since", "team",
            "fabric_ordered_at", "fabric_arrived_at", "sew_at", "cover_ready_at", "work_at", "fg_at",
            "indiv", "indiv_note", "due_at", "warnings",
            "fabrics", "manager", "created_at",
            "trashed_at", "trash_reason", "trash_reason_label", "purge_at",
            "passport_printed_at", "changed_at",
        ]

    @extend_schema_field(ItemFabricSerializer(many=True))
    def get_fabrics(self, obj):
        order = list(FabricSlot.values)
        rows = sorted(obj.fabrics.all(), key=lambda f: order.index(f.slot))
        return ItemFabricSerializer(rows, many=True).data

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(choices=["fabric", "cut", "output"])))
    def get_warnings(self, obj):
        return obj.warnings(self.context.get("today"), self.context.get("deadlines"))

    @extend_schema_field(OpenApiTypes.DATE)
    def get_purge_at(self, obj):
        deadlines = self.context.get("deadlines")
        if not obj.trashed_at or not deadlines:
            return None
        return timezone.localtime(obj.trashed_at).date() + timedelta(days=deadlines.trash_days)


class EventSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    item = serializers.SerializerMethodField()
    kind_label = serializers.CharField(source="get_kind_display")

    class Meta:
        model = ItemEvent
        fields = ["id", "at", "user", "item", "kind", "kind_label", "text", "data"]

    @extend_schema_field(RefSerializer)
    def get_user(self, obj):
        return {"id": obj.user_id, "name": obj.user.short_name}

    @extend_schema_field(ItemRefSerializer)
    def get_item(self, obj):
        return {"id": obj.item_id, "number": obj.item.number}


class ItemDetailSerializer(ItemSerializer):
    events = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta(ItemSerializer.Meta):
        fields = ItemSerializer.Meta.fields + ["events", "actions"]

    @extend_schema_field(EventSerializer(many=True))
    def get_events(self, obj):
        events = obj.events.select_related("user", "item").order_by("-at", "-id")
        return EventSerializer(events, many=True).data

    @extend_schema_field(ActionSerializer(many=True))
    def get_actions(self, obj):
        return available_actions(self.context["request"].user, obj)


class FabricInputSerializer(serializers.Serializer):
    slot = serializers.ChoiceField(choices=FabricSlot.choices)
    fabric = serializers.PrimaryKeyRelatedField(queryset=Fabric.objects.all())
    meters = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, required=False, allow_null=True)
    unit = serializers.ChoiceField(choices=AmountUnit.choices, required=False, default=AmountUnit.METERS)


class FabricAmountSerializer(serializers.Serializer):
    slot = serializers.ChoiceField(choices=FabricSlot.choices)
    meters = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, allow_null=True)
    unit = serializers.ChoiceField(choices=AmountUnit.choices, required=False, default=AmountUnit.METERS)


class ItemCreateSerializer(serializers.Serializer):
    model = serializers.PrimaryKeyRelatedField(queryset=ProductModel.objects.all(), required=False, allow_null=True)
    custom_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    fabrics = FabricInputSerializer(many=True)
    extra = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    reserve = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    indiv = serializers.BooleanField(required=False, default=False)
    indiv_note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    table_no = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    qty = serializers.IntegerField(min_value=1, max_value=MAX_QTY, required=False, default=1)


class ItemUpdateSerializer(serializers.Serializer):
    model = serializers.PrimaryKeyRelatedField(queryset=ProductModel.objects.all(), required=False, allow_null=True)
    custom_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    fabrics = FabricInputSerializer(many=True, required=False)
    extra = serializers.CharField(max_length=500, required=False, allow_blank=True)
    indiv = serializers.BooleanField(required=False)
    indiv_note = serializers.CharField(max_length=300, required=False, allow_blank=True)
    comment = serializers.CharField(required=False, allow_blank=True)
    table_no = serializers.CharField(max_length=30, required=False, allow_blank=True)


class MoveSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=Stage.choices)
    team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False, allow_null=True)
    date = serializers.DateField(required=False, allow_null=True, help_text="только для СГП: дата перевода")


class BulkMoveSerializer(MoveSerializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=500)


class UnmarkSerializer(serializers.Serializer):
    mark = serializers.ChoiceField(choices=["fabric_ordered", "fabric_arrived", "sew", "cover_ready"])


class MarkDateSerializer(serializers.Serializer):
    mark = serializers.ChoiceField(choices=["fabric_ordered", "fabric_arrived", "sew", "cover_ready", "fg"])
    date = serializers.DateField()


class ReserveSerializer(serializers.Serializer):
    reserve = serializers.CharField(max_length=300, allow_blank=True)
