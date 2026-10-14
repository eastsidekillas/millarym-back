from .base import *  # noqa: F401,F403

DEBUG = False
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
COOKIE_SECURE = False
for _k in ("ACCESS_TOKEN", "REFRESH_TOKEN"):
    SIMPLE_JWT["COOKIE_SETTINGS"][_k]["secure"] = False  # noqa: F405
