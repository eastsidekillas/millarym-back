import re
from pathlib import Path

from django.contrib.auth import get_user_model
from rest_framework import serializers

from app_catalog.serializers import FileUrlField, check_photo_size
from app_production.models import Item

from .models import CLOSED_STATES, Claim, ClaimFile, ClaimPhoto, ClaimState, ClaimType, DefectType, Sender

User = get_user_model()

EDITABLE = [
    "act_date", "manager", "counterparty", "item", "product", "item_number", "color", "part", "description",
    "package_data", "waybill", "sender", "invoice_price", "customer_shipped_at", "demands",
    "claim_type", "arrived_at", "kit", "sent_back_at",
    "appearance", "research", "defect_type", "remedy",
    "restore_cost", "finance_note", "video_links",
]
FILE_TYPES = {".doc", ".docx", ".pdf", ".odt", ".rtf", ".txt", ".xls", ".xlsx", ".ods", ".jpg", ".jpeg", ".png"}
MAX_FILE_MB = 15
MAX_LINKS = 20


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


class ClaimFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)
    url = serializers.SerializerMethodField()
    created_by = PersonField(read_only=True)

    class Meta:
        model = ClaimFile
        fields = ["id", "file", "name", "url", "size", "created_at", "created_by"]
        read_only_fields = ["name", "size", "created_at"]

    def get_url(self, obj) -> str:
        return obj.file.url if obj.file else ""

    def validate_file(self, file):
        suffix = Path(file.name).suffix.lower()
        if suffix not in FILE_TYPES:
            raise serializers.ValidationError("Такой файл не подходит: нужен Word, PDF, Excel или картинка.")
        if file.size > MAX_FILE_MB * 1024 * 1024:
            raise serializers.ValidationError(f"Файл больше {MAX_FILE_MB} МБ.")
        return file

    def create(self, validated_data):
        file = validated_data["file"]
        validated_data["name"] = Path(file.name).name[:255]
        validated_data["size"] = file.size
        return super().create(validated_data)


class ClaimListSerializer(serializers.ModelSerializer):
    manager = PersonField(read_only=True)
    claim_type_label = serializers.CharField(source="get_claim_type_display", read_only=True)
    defect_type_label = serializers.CharField(source="get_defect_type_display", read_only=True)
    photos_count = serializers.IntegerField(read_only=True, default=0)
    state_label = serializers.CharField(source="get_state_display", read_only=True)

    class Meta:
        model = Claim
        fields = [
            "id", "number", "act_date", "created_at", "manager", "counterparty", "product", "item_number",
            "description", "claim_type", "claim_type_label", "defect_type", "defect_type_label", "photos_count",
            "state", "state_label", "closed_at",
        ]


class ClaimSerializer(serializers.ModelSerializer):
    manager = PersonField(queryset=User.objects.filter(is_active=True), allow_null=True, required=False)
    item = ItemLinkField(queryset=Item.all_objects.all(), allow_null=True, required=False)
    claim_type_label = serializers.CharField(source="get_claim_type_display", read_only=True)
    defect_type_label = serializers.CharField(source="get_defect_type_display", read_only=True)
    sender_label = serializers.CharField(source="get_sender_display", read_only=True)
    state_label = serializers.CharField(source="get_state_display", read_only=True)
    closed_by = PersonField(read_only=True)
    photos = ClaimPhotoSerializer(many=True, read_only=True)
    files = ClaimFileSerializer(many=True, read_only=True)
    created_by = PersonField(read_only=True)
    updated_by = PersonField(read_only=True)

    class Meta:
        model = Claim
        fields = [
            "id", "number", *EDITABLE, "claim_type_label", "defect_type_label", "sender_label",
            "state", "state_label", "closed_at", "closed_by", "close_note",
            "photos", "files", "created_at", "created_by", "updated_at", "updated_by",
        ]
        read_only_fields = ["number", "state", "closed_at", "close_note", "created_at", "updated_at"]

    def validate_video_links(self, links):
        if not isinstance(links, list):
            raise serializers.ValidationError("Нужен список ссылок.")
        cleaned = []
        for link in links:
            link = str(link or "").strip()
            if not link:
                continue
            if not re.match(r"^https?://\S+$", link) or len(link) > 500:
                raise serializers.ValidationError(f"Это не ссылка: «{link[:60]}». Ссылка начинается с http:// или https://")
            if link not in cleaned:
                cleaned.append(link)
        if len(cleaned) > MAX_LINKS:
            raise serializers.ValidationError(f"Не больше {MAX_LINKS} ссылок.")
        return cleaned

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


CHOICES = {
    "claim_type": choices(ClaimType),
    "defect_type": choices(DefectType),
    "sender": choices(Sender),
    "state": choices(ClaimState),
}


class CloseSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=[(s.value, s.label) for s in CLOSED_STATES])
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
