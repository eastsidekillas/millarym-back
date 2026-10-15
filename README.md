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

Тестовые данные (только при `DEBUG=True`): `python manage.py seed_demo` — 7 сотрудников
с паролем `milarum2026`, модели, ткани, бригады и 60 изделий с историей за полтора месяца.
Повторно — `--append`, другой пароль — `--password`.

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
- Блокировка после неверных паролей пока выключена (CRM только в локальной сети).
  Когда откроем доступ из интернета — `AXES_ENABLED=True` в `.env`: 5 неверных паролей
  подряд → вход по этому логину закрыт на 15 минут. Снять раньше:
  `django-admin axes_reset_username <логин>` или в админке.
- `GET /api/v1/users/me/` — кто вошёл, его роль и коды прав.
- `POST /api/v1/users/password/` — смена своего пароля.
- `POST /api/v1/token/refresh/`, `POST /api/v1/users/logout/`.

## Справочники

Читать может любой вошедший, менять — с правом `fabrics` (ткани) или `catalog` (остальное).
Удаления нет — `active: false`.

| Адрес | Что | Фильтры |
| --- | --- | --- |
| `/api/v1/categories/` | категории | `active`, `search` |
| `/api/v1/models/` | модели, фото | `active`, `category`, `search` |
| `/api/v1/fabrics/` | ткани, фото (постранично) | `active`, `search`, `limit`, `offset` |
| `/api/v1/kit-options/` | комплектация для быстрых кнопок | `active` |
| `/api/v1/teams/` | бригады | `active`, `search` |
| `/api/v1/deadlines/` | сроки (GET / PATCH) | — |

Загрузить список моделей из Excel или CSV (колонки «Название» и «Категория»):
`python manage.py import_models models.xlsx --dry-run` — сначала проверка, потом без `--dry-run`.
Уже заведённые модели и повторы в файле пропускаются; `--create-categories` заводит новые категории,
`--category «Кресла»` — одна категория на весь файл, `--update-category` — поправить категорию у существующих.

Фото загружаются `multipart/form-data` (поле `photo`, до 15 МБ), сервер сохраняет WebP до 1600 px
и превью 300 px; `photo: null` убирает фото. Старые файлы удаляются при замене.

## Производство

Все запросы — для любого вошедшего; права проверяются на каждом действии (403 «Нет прав… Могут: …»),
ошибки правил — 400 `{"detail": "…"}`.

| Запрос | Что |
| --- | --- |
| `GET /api/v1/items/` | список: `stage` (orders, cut, cover, work, fg, trash), `q`, `model` (id через запятую), `free`, `reserved`, `indiv`, `late`, `ordering`, `limit`/`offset`. Без `stage` — все этапы кроме Корзины |
| `GET /api/v1/items/counters/` | количество и просроченные по этапам, свободные, Корзина |
| `GET /api/v1/items/{id}/` | карточка: поля, ткани, история `events`, кнопки `actions` (`allowed` и `reason` «Могут: …») |
| `POST /api/v1/items/` | завести (`qty` до 50), ответ — список созданных |
| `PATCH /api/v1/items/{id}/` | модель, комплектация, комментарий, индивидуальный, ткани |
| `POST /api/v1/items/{id}/move/` | `{to, team?}`; через этап или назад — право «Переместить в…» |
| `POST /api/v1/items/bulk-move/` | `{ids, to, team?}` — всё или ничего |
| `POST /api/v1/items/{id}/fabric-arrived/` · `sew/` · `cover-ready/` | отметки |
| `POST /api/v1/items/{id}/reserve/` | `{reserve}`, пустая строка — снять |
| `POST /api/v1/items/{id}/ship/` · `trash/` · `restore/` · `return-to-work/` · `copy/` | действия |
| `GET /api/v1/events/` | журнал: `user`, `item`, `kind`, `from`, `to` (ГГГГ-ММ-ДД), `q` |
| `GET /api/v1/users/` | сотрудники (для фильтра журнала) |

Поиск: `26/7965` — точный номер, `7965` — номер в любом году, иначе — модель, комплектация, резерв,
ткань, бригада, комментарий (без учёта регистра, индексы `pg_trgm`).

## Отчёты

Доступны всем вошедшим. `GET /api/v1/reports/` — список с параметрами; `GET /api/v1/reports/{kind}/` —
таблица для предпросмотра (JSON); `GET /api/v1/reports/{kind}/xlsx/` — тот же отчёт в Excel
(логотип, фото тканей, группы, лист «Итог»). `GET /api/v1/items/{id}/export/` — одно изделие в Excel.

| kind | Отчёт | Параметры |
| --- | --- | --- |
| `free-stock` | Свободные остатки | `models` (id через запятую, `custom` — вне справочника) |
| `reserved` | Зарезервированные по контрагенту, с группами и итогом по моделям | `q`, `only_fg` |
| `orders-period` | Заказы за период | `from`, `to` |
| `orders-by-reserve` | Заказы по контрагенту, включая отгруженные | `q` |
| `orders-by-model` | Заказы по модели | `models` |
| `no-fabric` | Не пришла ткань | — |
| `overdue` | Заказы с просроком | — |

`GET /api/v1/reports/free-stock/models/` — модели, у которых есть свободные изделия, и сколько их.
Поиск по резерву не различает регистр и «е/ё».

## Корзина, фоновые задачи и резервные копии

Отгруженные и удалённые изделия лежат в Корзине 30 дней (срок — `trash_days` в `/api/v1/deadlines/`), потом
удаляются окончательно: пропадают из списков, поиска, остатков и счётчиков, но запись в базе и история в журнале
остаются (`purged_at`). Отчёты по заказам (за период, по контрагенту, по модели) отгруженные показывают и после этого. Карточка такого изделия отвечает 404 «удалено из Корзины окончательно ДД.ММ.ГГ».

```bash
python manage.py purge_trash --dry-run   # что удалится
python manage.py purge_trash             # удалить
```

В Docker это делают два контейнера:

- `scheduler` — `django-admin scheduler --at 03:00`: каждую ночь в 03:00 по времени фабрики чистит Корзину;
- `backup` — каждую ночь в 02:30 кладёт в `./backups` (рядом с `docker-compose.yml`, другая папка — `BACKUP_DIR`
  в `.env`) дамп базы `db_ГГГГ-ММ-ДД_ЧЧММ.dump` и архив фото `media_….tar.gz`; копии старше 14 дней удаляются.
  Сделать копию сразу: `docker compose run --rm backup --now` (после неё контейнер продолжит ждать ночи — Ctrl+C).

Копии лежат на том же сервере — раз в неделю переносите свежую на другой диск или в облако.

Восстановить:

```bash
docker compose stop app scheduler
docker compose exec -T postgres pg_restore -U millarym -d millarym --clean --if-exists < backups/db_2026-10-15_0230.dump
docker compose run --rm -v "$PWD/backups:/backups" --entrypoint tar app -xzf /backups/media_2026-10-15_0230.tar.gz -C /app/media
docker compose start app scheduler
```

## Паспорт изделия

`GET /api/v1/passports/?ids=1,2,3` — PDF (A4, на изделие лист с отрывным ярлыком внизу), до 200 изделий за раз.
QR-код ведёт в карточку: адрес CRM берётся из `SITE_URL` в `.env`. Открытие паспорта отмечает изделие как напечатанное
(`passport_printed_at`, событие в истории). Если потом поменять то, что есть в паспорте (название, комплектацию,
ткани, индивидуальный, резерв), у изделия появляется `passport_outdated: true` — паспорт нужно перепечатать.
Комментарий в паспорт не входит и на отметку не влияет.

Вёрстка — `app_reports/templates/reports/passport.html`, шрифт Golos Text лежит в `app_reports/assets/fonts`.
PDF собирает WeasyPrint, ему нужна системная библиотека Pango. В Docker она ставится в образе,
на Mac — `brew install pango`. На Apple Silicon Homebrew кладёт библиотеки в `/opt/homebrew/lib`;
бэкенд сам ищет их там, переменные окружения не нужны. Без Pango остальная CRM работает,
не собирается только паспорт.

Права — коды в `app_auth/rights.py`, роли — группы Django.
Матрица ролей задаётся в `ROLES`; при `migrate` группы создаются, но существующие
не перезаписываются. Вернуть матрицу из кода: `django-admin setup_roles --reset`.

В представлениях право проверяется так:

```python
from app_auth.permissions import HasRight

class ShipView(APIView):
    permission_classes = [HasRight("ship")]
```
