from .base import *  # noqa: F401,F403
from .base import config, Csv

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

# Фронт в разработке ходит через proxy.conf.json Angular (тот же origin),
# но оставляем CORS для прямых запросов с localhost:4200
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="http://localhost:4200", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="http://localhost:4200", cast=Csv())
