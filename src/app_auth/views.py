from django.conf import settings
from django.contrib.auth import authenticate, user_logged_in
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .serializers import LoginSerializer, MeSerializer, PasswordChangeSerializer, UserShortSerializer


def _cookie(name: str) -> dict:
    return settings.SIMPLE_JWT["COOKIE_SETTINGS"][name]


def _set_token_cookie(response: Response, name: str, value: str) -> None:
    c = _cookie(name)
    response.set_cookie(
        key=c["key"],
        value=value,
        expires=timezone.now() + settings.SIMPLE_JWT[f"{name}_LIFETIME"],
        httponly=c["httponly"],
        secure=c["secure"],
        samesite=c["samesite"],
        path=c["path"],
    )


def _clear_token_cookies(response: Response) -> None:
    for name in ("ACCESS_TOKEN", "REFRESH_TOKEN"):
        c = _cookie(name)
        response.delete_cookie(c["key"], path=c["path"], samesite=c["samesite"])


class LoginAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=LoginSerializer, responses=MeSerializer)
    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        # axes работает с исходным HttpRequest
        user = authenticate(
            request=request._request,
            username=s.validated_data["login"],
            password=s.validated_data["password"],
        )
        if user is None:
            return Response({"detail": "Неверный логин или пароль."}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        response = Response(MeSerializer(user).data)
        _set_token_cookie(response, "ACCESS_TOKEN", str(refresh.access_token))
        _set_token_cookie(response, "REFRESH_TOKEN", str(refresh))
        user_logged_in.send(sender=user.__class__, request=request._request, user=user)
        return response


class TokenRefreshAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        raw = request.COOKIES.get(_cookie("REFRESH_TOKEN")["key"])
        if not raw:
            return Response({"detail": "Нужно войти заново."}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            refresh = RefreshToken(raw)
        except TokenError:
            response = Response({"detail": "Сессия истекла, войдите заново."}, status=status.HTTP_401_UNAUTHORIZED)
            _clear_token_cookies(response)
            return response
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _set_token_cookie(response, "ACCESS_TOKEN", str(refresh.access_token))
        return response


class LogoutAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _clear_token_cookies(response)
        return response


class MeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class PasswordChangeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    def post(self, request):
        s = PasswordChangeSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        request.user.set_password(s.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserListAPIView(generics.ListAPIView):
    serializer_class = UserShortSerializer
    pagination_class = None

    def get_queryset(self):
        return User.objects.filter(is_active=True, is_superuser=False).order_by("last_name").prefetch_related("groups")
