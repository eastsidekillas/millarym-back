from rest_framework import serializers
from rest_framework.fields import empty

from .images import jpeg_url
from .models import Category, Deadlines, Fabric, KitOption, ProductModel, Team

MAX_PHOTO_MB = 15


class FileUrlField(serializers.ImageField):
    def to_representation(self, value):
        return value.url if value else None


def check_photo_size(photo):
    if photo and photo.size > MAX_PHOTO_MB * 1024 * 1024:
        raise serializers.ValidationError(f"Фото больше {MAX_PHOTO_MB} МБ.")
    return photo


class KeepBoolean(serializers.BooleanField):
    default_empty_html = empty


class PhotoSerializerMixin(serializers.Serializer):
    photo = FileUrlField(required=False, allow_null=True)
    active = KeepBoolean(required=False)
    photo_thumb = FileUrlField(read_only=True)

    def validate_photo(self, photo):
        return check_photo_size(photo)

    def update(self, instance, validated_data):
        if "photo" in validated_data and validated_data["photo"] is None:
            validated_data["photo"] = ""
        return super().update(instance, validated_data)


class UniqueNameMixin:
    def validate_name(self, name):
        name = name.strip()
        qs = self.Meta.model.objects.filter(name__iexact=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"«{name}» уже есть в справочнике.")
        return name


class CategorySerializer(UniqueNameMixin, serializers.ModelSerializer):
    models_count = serializers.IntegerField(read_only=True, default=0)
    used = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ["id", "name", "sort", "active", "models_count", "used"]


MAX_KIT_OPTIONS = 30


class ProductModelSerializer(PhotoSerializerMixin, UniqueNameMixin, serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    in_work = serializers.IntegerField(read_only=True, default=0)
    used = serializers.IntegerField(read_only=True, default=0)
    kit_options = serializers.ListField(
        child=serializers.CharField(max_length=120, allow_blank=True), required=False, max_length=MAX_KIT_OPTIONS
    )
    photo_jpeg = serializers.SerializerMethodField()

    def validate_kit_options(self, options):
        cleaned = []
        for option in options:
            option = " ".join(option.split())
            if not option:
                continue
            # в «Комплектации» изделия пункты разделяются запятой
            if "," in option:
                raise serializers.ValidationError(f"Без запятых: «{option}». Например, «Подушки-подголовники 3 шт.»")
            if option.lower() not in (o.lower() for o in cleaned):
                cleaned.append(option)
        return cleaned

    class Meta:
        model = ProductModel
        fields = [
            "id", "name", "category", "category_name", "photo", "photo_thumb", "photo_jpeg", "active", "kit_options",
            "in_work", "used",
        ]

    def get_photo_jpeg(self, obj) -> str | None:
        return jpeg_url("models", obj)


class FabricSerializer(PhotoSerializerMixin, UniqueNameMixin, serializers.ModelSerializer):
    in_work = serializers.IntegerField(read_only=True, default=0)
    used = serializers.IntegerField(read_only=True, default=0)
    photo_jpeg = serializers.SerializerMethodField()

    class Meta:
        model = Fabric
        fields = ["id", "name", "photo", "photo_thumb", "photo_jpeg", "active", "created_at", "in_work", "used"]

    def get_photo_jpeg(self, obj) -> str | None:
        return jpeg_url("fabrics", obj)


class KitOptionSerializer(UniqueNameMixin, serializers.ModelSerializer):
    used = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = KitOption
        fields = ["id", "name", "sort", "active", "used"]


class TeamSerializer(UniqueNameMixin, serializers.ModelSerializer):
    used = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Team
        fields = ["id", "name", "foreman", "sort", "active", "used"]


class DeadlinesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deadlines
        fields = ["fabric_days", "cut_days", "output_days", "trash_days"]
        extra_kwargs = {f: {"min_value": 1, "max_value": 365} for f in fields}
