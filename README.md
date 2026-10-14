# millarym-back

Бэкенд CRM фабрики «Миларум»: Django 5.2 + DRF + PostgreSQL 16.
Фронтенд — соседний репозиторий `../millarym-front` (Angular 20 + Tailwind).

## Структура

```
millarym-back/
├── Dockerfile            # poetry → python:3.12-slim + gunicorn
├── docker-compose.yml    # app, migration, collectstatic, postgres, frontend (../millarym-front)
├── example.env           # образец .env
├── pyproject.toml
└── src/
    ├── manage.py
    ├── millarym_core/    # настройки (settings/base|dev|prod|test), urls, обработчик ошибок
    └── app_auth/         # пользователи, вход, роли и права
```

Настройки выбираются переменной `DJANGO_ENV`: `dev` (по умолчанию), `prod`, `test`.

## Локальный запуск

```bash
cp example.env .env                     # заполнить DJANGO_SECRET_KEY
poetry lock && poetry install
docker compose up -d postgres           # или свой PostgreSQL
cd src
python manage.py migrate                # создаёт 6 ролей с правами
python manage.py create_users           # 7 сотрудников, печатает пароли ОДИН раз
python manage.py runserver
```

Документация API: http://localhost:8000/api/v1/docs/

Тесты: `DJANGO_ENV=test python manage.py test` (SQLite в памяти).

## Сервер (Docker)

Рядом должны лежать оба репозитория: `millarym/millarym-back` и `millarym/millarym-front`.

```bash
cd millarym-back
cp example.env .env                     # DJANGO_ENV=prod, DEBUG=False, ALLOWED_HOSTS=<адрес сервера>
docker compose up -d --build
docker compose run --rm app django-admin create_users
```

Сайт открывается на порту 8000 (nginx из millarym-front проксирует `/api` и `/admin` в Django).

## Вход и права

- Вход по логину **или** почте (`POST /api/v1/users/login/`), токены JWT в httpOnly cookie.
- 5 неверных паролей подряд → вход по этому логину заблокирован на 15 минут.
  Снять раньше: `django-admin axes_reset_username <логин>` или в админке.
- `GET /api/v1/users/me/` — кто вошёл, его роль и коды прав.
- `POST /api/v1/users/password/` — смена своего пароля.
- `POST /api/v1/token/refresh/`, `POST /api/v1/users/logout/`.

Права (spec 08 §2.0) — коды в `app_auth/rights.py`, роли — группы Django.
Матрица ролей задаётся в `ROLES`; при `migrate` группы создаются, но существующие
не перезаписываются. Вернуть матрицу из кода: `django-admin setup_roles --reset`.

В представлениях право проверяется так:

```python
from app_auth.permissions import HasRight

class ShipView(APIView):
    permission_classes = [HasRight("ship")]
```
