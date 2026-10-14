import os
from datetime import timedelta
from pathlib import Path

from decouple import Csv, config
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

AUTH_USER_MODEL = "app_auth.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "rest_framework_simplejwt",
    "axes",
    "app_auth",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Должен быть последним: блокирует вход после N неверных паролей
    "axes.middleware.AxesMiddleware",
]

# Порядок важен: сначала axes (блокировка), затем вход по логину или почте
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "app_auth.backends.LoginOrEmailBackend",
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": (
        ["rest_framework.renderers.JSONRenderer"]
        if not DEBUG
        else [
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        ]
    ),
    # Всё закрыто по умолчанию: без входа приложение недоступно
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["app_auth.authentication.CookieJWTAuthentication"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "millarym_core.exceptions.core_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Миларум CRM API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

COOKIE_SECURE = config("COOKIE_SECURE", default=True, cast=bool)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=config("ACCESS_TOKEN_LIFETIME", default=8, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=config("REFRESH_TOKEN_LIFETIME", default=14, cast=int)),
    "UPDATE_LAST_LOGIN": True,
    "COOKIE_SETTINGS": {
        "ACCESS_TOKEN": {
            "key": "access_token",
            "httponly": True,
            "secure": COOKIE_SECURE,
            "samesite": "Strict",
            "path": "/",
        },
        "REFRESH_TOKEN": {
            "key": "refresh_token",
            "httponly": True,
            "secure": COOKIE_SECURE,
            "samesite": "Strict",
            # refresh-cookie уходит только на эндпоинт обновления
            "path": "/api/v1/token/refresh/",
        },
    },
}

# Блокировка после неверных паролей (spec 08 §2.0). Пока CRM работает только
# в локальной сети — выключена; включить (AXES_ENABLED=True), когда откроем доступ
# из интернета. Считается по логину, не по IP — в офисе у всех один адрес.
AXES_ENABLED = config("AXES_ENABLED", default=False, cast=bool)
AXES_FAILURE_LIMIT = config("AXES_FAILURE_LIMIT", default=5, cast=int)
AXES_COOLOFF_TIME = timedelta(minutes=config("AXES_COOLOFF_MINUTES", default=15, cast=int))
AXES_LOCKOUT_PARAMETERS = ["username"]
SILENCED_SYSTEM_CHECKS = ["axes.W006"]  # блокируем по логину осознанно (один IP на офис)
AXES_RESET_ON_SUCCESS = True
AXES_USERNAME_CALLABLE = "app_auth.axes_hooks.username_for_lockout"
AXES_LOCKOUT_CALLABLE = "app_auth.axes_hooks.lockout_response"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "millarym_core.wsgi.application"
ROOT_URLCONF = "millarym_core.urls"

DATABASES = {
    "default": {
        "ENGINE": config("DATABASE_ENGINE", default="django.db.backends.postgresql"),
        "NAME": config("DATABASE_NAME", default="millarym"),
        "USER": config("DATABASE_USER", default="millarym"),
        "PASSWORD": config("DATABASE_PASSWORD", default="millarym"),
        "HOST": config("DATABASE_HOST", default="localhost"),
        "PORT": config("DATABASE_PORT", default="5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Yekaterinburg"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = os.getenv("STATIC_ROOT", BASE_DIR / "static")

MEDIA_ROOT = os.getenv("MEDIA_ROOT", BASE_DIR / "media")
MEDIA_URL = os.getenv("MEDIA_URL", "/media/")
