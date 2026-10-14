from .base import *  # noqa: F401,F403
from .base import COOKIE_SECURE, config, Csv

DEBUG = False

ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# Безопасность. Пока сервер в локальной сети по HTTP — COOKIE_SECURE=False;
# при выходе наружу по HTTPS включить COOKIE_SECURE=True
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = COOKIE_SECURE
CSRF_COOKIE_SECURE = COOKIE_SECURE
SECURE_REFERRER_POLICY = "same-origin"
if COOKIE_SECURE:
    SECURE_HSTS_SECONDS = 31536000
