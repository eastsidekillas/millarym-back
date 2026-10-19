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

## Сервер с доменом (HTTPS)

Нужны Ubuntu или Debian с доступом root и домен, у которого запись A указывает на сервер. На сервере:

```bash
curl -fsSL https://raw.githubusercontent.com/eastsidekillas/millarym-front/main/deploy/server-setup.sh | bash -s -- test.chillgate.cc
```

Скрипт ставит Docker, скачивает оба репозитория в `/opt/millarym`, создаёт `.env` (случайные секретный ключ и
пароль базы, HTTPS-куки, защита от подбора пароля включена), собирает и запускает всё вместе с Caddy — он сам
получает сертификат Let's Encrypt (`deploy/compose.server.yml`, `deploy/Caddyfile`). Наружу открыты только 80 и 443.
При первом запуске загружает справочник моделей и заводит сотрудников — логины и пароли в `/root/millarym-passwords.txt`.

`millarym-back` приватный: при первом запуске скрипт покажет ключ сервера — добавить его в GitHub →
Settings → Deploy keys (только чтение) и запустить скрипт ещё раз. Обновить сервер — тот же запуск:
`bash /opt/millarym/millarym-front/deploy/server-setup.sh test.chillgate.cc`. Лог — `/opt/millarym/deploy.log`.

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

Справочник моделей фабрики (160 позиций, 15.10.2026) лежит в `data/models-2026-10-15.csv`. Загрузить в новую базу:
`python manage.py import_models ../data/models-2026-10-15.csv --create-categories` (из папки `src`).
Категории расставлены по названию и правятся в справочнике.

Загрузить список моделей из Excel или CSV (колонки «Название» и «Категория»):
`python manage.py import_models models.xlsx --dry-run` — сначала проверка, потом без `--dry-run`.
Уже заведённые модели и повторы в файле пропускаются; `--create-categories` заводит новые категории,
`--category «Кресла»` — одна категория на весь файл, `--update-category` — поправить категорию у существующих.

Фото тканей пачкой: `python manage.py import_fabrics ткани.zip --dry-run` (zip или папка) — название ткани
берётся из имени файла (`Arben_ultra_grafit.jpg` → «Arben ultra grafit»), регистр не важен; новых тканей нет — заводятся
(`--no-create` — только фото к уже заведённым), фото у ткани уже есть — не трогаем (`--replace` — заменить).
На сервере: `bash deploy/import-fabrics.sh /root/ткани.zip --dry-run`, затем без `--dry-run`.

Фото загружаются `multipart/form-data` (поле `photo`, до 15 МБ), сервер сохраняет WebP до 1600 px
и превью 300 px; `photo: null` убирает фото. Старые файлы удаляются при замене.

## Производство

Все запросы — для любого вошедшего; права проверяются на каждом действии (403 «Нет прав… Могут: …»),
ошибки правил — 400 `{"detail": "…"}`.

| Запрос | Что |
| --- | --- |
| `GET /api/v1/items/` | список: `stage` (orders, cut, cover, work, fg, trash), `q`, `model` (id через запятую), `free`, `reserved`, `indiv`, `late`, `ordering`, `limit`/`offset`. Без `stage` — все этапы кроме Корзины; с `q` без `stage` — ещё и Корзина (в конце списка) |
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

## Рекламации

Акт-претензия по форме фабрики: сведения от клиента, разделы менеджера и мастера цеха, финансовая часть, фото брака
(WebP, как у тканей). Номер акта — `ГГ/NNN`, по порядку в году. Привязка к изделию необязательна: рекламация может
прийти через годы, когда изделие уже удалено из Корзины. Читать могут все, заводить и менять — с правом `claims`
(директор, руководитель швейного цеха, менеджеры, мастер мягкого цеха). Удаления нет.

| Запрос | Что |
| --- | --- |
| `GET/POST /api/v1/claims/` | список (`q`, `claim_type`, `defect_type`, `sender`, `from`, `to`, `limit`/`offset`) и новая |
| `GET/PATCH /api/v1/claims/{id}/` | карточка и правка |
| `POST /api/v1/claims/{id}/photos/` · `DELETE …/photos/{photo_id}/` | фото |
| `GET /api/v1/claims/stats/` | сколько по виду дефекта и типу претензии (те же фильтры) |
| `GET /api/v1/claims/choices/` | списки: тип претензии, вид дефекта, отправитель |
| `GET /api/v1/claims/{id}/pdf/` | акт для покупателя (без финансовой части) |
| `GET /api/v1/claims/blank/` | пустой бланк для клиента в Excel |

Отчёт «Рекламации» за период (группы по виду дефекта, итог по типу претензии, Excel) — `GET /api/v1/reports/claims/`.

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
(`passport_printed_at`, событие в истории).

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

## Перенос из старых систем

`python manage.py import_legacy --reserv reserv_db2.sql --orders zakaz.sql --dry-run` — дампы phpMyAdmin читаются
напрямую, MySQL не нужен. С `--dry-run` только отчёт, без него — запись; повторный запуск дублей не создаёт.
На сервере: `bash deploy/import-legacy.sh /root/reserv_db2.sql /root/zakaz.sql --dry-run` (отчёт ещё и в `/root/legacy-report-*.txt`).

Что переносится:
- **Резервы** — все строки со складом 1–4 (4 Крой, 2 Склад чехлов, 3 В работе, 1 СГП), кроме «СТОП». Строки без склада
  (старые, в старой системе не видны) и Корзина (`trash`) не переносятся.
- **Заказы** — с `--since` (по умолчанию 01.01.2026), не отгруженные и не снятые («снят»/«отмена» в комментарии).
  Если в резервах есть изделие с этим номером («(Заказ №9578)») — это одно изделие: этап и ткани из резервов,
  менеджер, дата заведения, «ткань пришла» и метраж — из заказа. Заказ без изделия в резервах и без кроя → «Заказы»
  (без контрагента → «Крой»), «- 2 штуки» — два изделия. Раскроенный заказ без изделия в резервах не переносится,
  номер попадает в отчёт.

Как сопоставляется:
- Номер — новый `ГГ/NNNN`; старый в «Номер в старой системе» (`114542 · 9578/ЗАК`), по нему работает поиск.
- Модель — по началу названия (без «диван», «БД», кавычек, дат, номера заказа; «(4 кат.)» — вариант «4 кат.»,
  «Кресло "Дубай М"» → «Дубай М кресло»). Остаток («Накладки белые», «правый») — в комплектацию. Не нашлась —
  «вне справочника» со старым названием; список — в отчёте: добавьте модели в справочник и запустите заново.
- Ткани — по имени файла, как в `import_fabrics`; сначала загрузите фото тканей. Не нашлась — заводится скрытой
  (у изделия есть, в выборе нет). Кожзам — в свободный компаньон, иначе в комментарий.
- Даты — из `в шитье 08.10. отшит 14.10.26`, «выдано в работу», «поступило на склад», даты в названии; что не
  разобралось — остаётся в комментарии. Бригада — по бригадиру (нет — заводится). Менеджер — по фамилии,
  иначе `--manager "Ольга Филина=postnikova"`; неизвестный → «Старая система» (неактивный пользователь `legacy`).
- В истории изделия — «Заведено в старой системе: «старое название»» и старые этапы с их датами.
