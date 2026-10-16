from django.contrib.auth import get_user_model
from rest_framework import serializers

from app_catalog.serializers import FileUrlField, check_photo_size
from app_production.models import Item

from .models import Claim, ClaimPhoto, ClaimType, DefectType, Sender

User = get_user_model()

EDITABLE = [
    "act_date", "manager", "counterparty", "item", "product", "item_number", "color", "part", "description",
    "package_data", "waybill", "sender", "invoice_price", "customer_shipped_at", "demands",
    "claim_type", "arrived_at", "kit", "sent_back_at",
    "appearance", "research", "defect_type", "remedy",
    "restore_cost", "finance_note",
]


class ClaimPhotoSerializer(serializers.ModelSerializer):
    photo = FileUrlField()
    photo_thumb = FileUrlField(read_only=True)

    class Meta:
        model = ClaimPhoto
        fields = ["id", "photo", "photo_thumb", "created_at"]

    def validate_photo(self, photo):
        return check_photo_size(photo)


class PersonField(serializers.PrimaryKeyRelatedField):
    def use_pk_only_optimization(self):
        return False

    def to_representation(self, value):
        return {"id": value.pk, "name": value.short_name}


class ItemLinkField(serializers.PrimaryKeyRelatedField):
    def use_pk_only_optimization(self):
        return False

    def to_representation(self, value):
        return {"id": value.pk, "number": value.number, "available": value.purged_at is None}


class ClaimListSerializer(serializers.ModelSerializer):
    manager = PersonField(read_only=True)
    claim_type_label = serializers.CharField(source="get_claim_type_display", read_only=True)
    defect_type_label = serializers.CharField(source="get_defect_type_display", read_only=True)
    photos_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Claim
        fields = [
            "id", "number", "act_date", "created_at", "manager", "counterparty", "product", "item_number",
            "description", "claim_type", "claim_type_label", "defect_type", "defect_type_label", "photos_count",
        ]


class ClaimSerializer(serializers.ModelSerializer):
    manager = PersonField(queryset=User.objects.filter(is_active=True), allow_null=True, required=False)
    item = ItemLinkField(queryset=Item.all_objects.all(), allow_null=True, required=False)
    claim_type_label = serializers.CharField(source="get_claim_type_display", read_only=True)
    defect_type_label = serializers.CharField(source="get_defect_type_display", read_only=True)
    sender_label = serializers.CharField(source="get_sender_display", read_only=True)
    photos = ClaimPhotoSerializer(many=True, read_only=True)
    created_by = PersonField(read_only=True)
    updated_by = PersonField(read_only=True)

    class Meta:
        model = Claim
        fields = [
            "id", "number", *EDITABLE, "claim_type_label", "defect_type_label", "sender_label",
            "photos", "created_at", "created_by", "updated_at", "updated_by",
        ]
        read_only_fields = ["number", "created_at", "updated_at"]

    def validate(self, attrs):
        for key in EDITABLE:
            if isinstance(attrs.get(key), str):
                attrs[key] = attrs[key].strip()
        item = attrs.get("item")
        if item and not self.instance:
            if not attrs.get("product"):
                attrs["product"] = f"{item.title}, {item.extra}" if item.extra else item.title
            if not attrs.get("item_number"):
                attrs["item_number"] = item.number
            if not attrs.get("color"):
                attrs["color"] = ", ".join(f.fabric.name for f in item.fabrics.select_related("fabric"))
            if not attrs.get("counterparty"):
                attrs["counterparty"] = item.reserve
        return attrs


def choices(enum) -> list[dict]:
    return [{"id": value, "name": label} for value, label in enum.choices]


CHOICES = {"claim_type": choices(ClaimType), "defect_type": choices(DefectType), "sender": choices(Sender)}
