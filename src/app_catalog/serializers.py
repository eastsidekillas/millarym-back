from rest_framework import serializers
from rest_framework.fields import empty

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


class ProductModelSerializer(PhotoSerializerMixin, UniqueNameMixin, serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    in_work = serializers.IntegerField(read_only=True, default=0)
    used = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ProductModel
        fields = ["id", "name", "category", "category_name", "photo", "photo_thumb", "active", "in_work", "used"]


class FabricSerializer(PhotoSerializerMixin, UniqueNameMixin, serializers.ModelSerializer):
    in_work = serializers.IntegerField(read_only=True, default=0)
    used = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Fabric
        fields = ["id", "name", "photo", "photo_thumb", "active", "created_at", "in_work", "used"]


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
