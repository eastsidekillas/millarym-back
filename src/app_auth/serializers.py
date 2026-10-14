from django.contrib.auth import password_validation
from rest_framework import serializers

from .models import User


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField(label="Логин или почта", max_length=254)
    password = serializers.CharField(label="Пароль", write_only=True, trim_whitespace=False)


class MeSerializer(serializers.ModelSerializer):
    short_name = serializers.CharField(read_only=True)
    role = serializers.CharField(source="role_name", read_only=True)
    groups = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    rights = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "last_name", "first_name", "short_name", "role", "groups", "rights"]


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Текущий пароль указан неверно.")
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, self.context["request"].user)
        return value


class UserShortSerializer(serializers.ModelSerializer):
    short_name = serializers.CharField(read_only=True)
    role = serializers.CharField(source="role_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "short_name", "role"]
