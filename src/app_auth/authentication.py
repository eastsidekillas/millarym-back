from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


class CookieJWTAuthentication(JWTAuthentication):
    """
    JWT из httpOnly-cookie (как в AFISHA_LESNOY). Нет cookie — не аутентифицирован
    (DRF ответит 401, фронт попробует обновить токен). Просроченный токен — 401.
    """

    def authenticate(self, request):
        key = settings.SIMPLE_JWT["COOKIE_SETTINGS"]["ACCESS_TOKEN"]["key"]
        raw = request.COOKIES.get(key)
        if not raw:
            return None
        try:
            token = self.get_validated_token(raw)
        except (InvalidToken, TokenError):
            raise InvalidToken("Сессия истекла, войдите заново.")
        return self.get_user(token), token


try:  # описание схемы входа для OpenAPI (Swagger на /api/v1/docs/)
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    class CookieJWTScheme(OpenApiAuthenticationExtension):
        target_class = "app_auth.authentication.CookieJWTAuthentication"
        name = "cookieAuth"

        def get_security_definition(self, auto_schema):
            return {"type": "apiKey", "in": "cookie", "name": "access_token"}
except ImportError:  # pragma: no cover
    pass
