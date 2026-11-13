# Выгрузка «Для номенклатурного плана»: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** В «Отчётах» появляется выгрузка `nomenclature`: менеджер отмечает партнёров и получает xlsx с колонками строго в порядке номенклатурного плана, без оформления.

**Architecture:** Новый отчёт в существующем реестре `REPORTS` (`app_reports/reports.py`) плюс эндпоинт списка партнёров по образцу `free-stock/models/`. `Result` получает флаг `plain`, и `build_xlsx` для него пишет голую таблицу. На фронте `ModelPickerComponent` получает подписи через входы и используется для нового типа параметра `partners`.

**Tech Stack:** Django 5 + DRF, openpyxl (бэк, `millarym-back`); Angular с сигналами, Tailwind (фронт, `millarym-front`).

**Spec:** `millarym-back/docs/superpowers/specs/2026-11-13-nomenclature-export-design.md`

## Global Constraints

- Колонки строго в этом порядке и с этими заголовками: `ID`, `Заказ`, `Наименование изделия`, `Цена`, `Угол`, `Накладки`, `Дополнение`, `Резерв`, `Менеджер`, `Склад`, `ВАЖНО`, `Дата отгр.`, `Бригада`.
- `Цена`, `ВАЖНО`, `Дата отгр.`, `Бригада` всегда пустые.
- Изделия в Корзине (`trashed_at` не пусто) не попадают никогда.
- `Склад` — названия этапов CRM (`Stage.label`).
- Остальные отчёты и их xlsx не меняются.
- Тесты бэка: `cd millarym-back/src && DJANGO_ENV=test <poetry venv>/bin/python manage.py test app_reports` (venv: `poetry env info -p`).

## Review Focus

1. Резерв с запятой («Копылова (8 Марта), Красноуфимск») выбирается как один партнёр — разделитель в параметре `|`, а не запятая.
2. Резервы, отличающиеся только пробелами по краям («Миларум розница» и «Миларум розница »), — один партнёр и в списке, и в выгрузке.
3. «Комплектация» со свободным текстом («правый угол, накладки венге, без ножек») не теряет хвост: «без ножек» уходит в `Дополнение`.
4. Старый номер с двумя заказами (`114542 · 9578/ЗАК · 9580/ЗАК`) даёт `9578, 9580`.
5. Изделие без менеджера с фамилией (пустой `last_name`) — в `Менеджер` попадает `username`, а не пусто и не падение.

---

### Task 1: Отчёт `nomenclature` и список партнёров (бэк)

**Files:**
- Modify: `millarym-back/src/app_reports/rows.py` (новые функции разбора)
- Modify: `millarym-back/src/app_reports/reports.py` (отчёт, `partners_list`, регистрация в `REPORTS`)
- Modify: `millarym-back/src/app_reports/views.py`, `urls.py` (эндпоинт `reports/nomenclature/partners/`)
- Test: `millarym-back/src/app_reports/tests.py`

**Interfaces:**
- Produces (rows.py):
  - `split_extra(extra: str) -> tuple[str, str, str]` — `(угол, накладки, остаток)`. Угол: `"Левый"` / `"Правый"` по словам на «лев» / «прав» (с «угол» или без); накладки: слово после «накладки», в нижнем регистре; остаток — прочие части через запятую, `", "`-джойн.
  - `order_numbers(legacy_number: str) -> str` — номера частей `NNNN/ЗАК` из `legacy_number`, разделённого `" · "`, через `", "`.
  - `manager_name(item: Item) -> str` — `item.manager.last_name.strip() or item.manager.username`.
- Produces (reports.py):
  - `PARTNER_SEP = "|"`
  - `partners_list() -> list[dict]` — `[{"id": str, "name": str, "count": int}]`, `id == name ==` резерв без пробелов по краям, только изделия не в Корзине с непустым резервом, сортировка `ru_key`.
  - `nomenclature(params: dict) -> Result` — параметр `partners` (строка, партнёры через `|`), `Result.plain = True` (поле добавляет Task 2; до тех пор не передавать), `filename = f"Номенклатура {params.get('_user', '')} {today_label()}"` с ужатыми пробелами.
  - Ключи ячеек: `number, order, item, price, corner, overlays, extra, reserve, manager, stage, important, ship_date, team`.
  - `PARTNERS_PARAM = Param("partners", "Партнёры", "partners", True)`.
  - В реестре: `Report("nomenclature", "Для номенклатурного плана", "Изделия выбранных партнёров на всех этапах, колонки — в порядке номенклатурного плана. Цена, ВАЖНО, дата отгрузки и бригада — пустые, их заполняют в плане.", [PARTNERS_PARAM], nomenclature)`.
- Produces (HTTP): `GET /api/v1/reports/nomenclature/partners/` → `partners_list()`.

- [ ] **Step 1: Write the failing tests**

```python
from app_reports.rows import order_numbers, split_extra

def test_split_extra(self):
    self.assertEqual(split_extra("левый угол, накладки венге"), ("Левый", "венге", ""))
    self.assertEqual(split_extra("Правый"), ("Правый", "", ""))
    self.assertEqual(split_extra("Накладки белые"), ("", "белые", ""))
    self.assertEqual(split_extra("правый угол, накладки венге, без ножек"), ("Правый", "венге", "без ножек"))
    self.assertEqual(split_extra(""), ("", "", ""))

def test_order_numbers(self):
    self.assertEqual(order_numbers("114542 · 9578/ЗАК"), "9578")
    self.assertEqual(order_numbers("114542 · 9578/ЗАК · 9580/ЗАК"), "9578, 9580")
    self.assertEqual(order_numbers("114542"), "")
    self.assertEqual(order_numbers(""), "")

def test_nomenclature(self):
    [a] = self.make(reserve="Фобос (Тура)", extra="правый угол, накладки венге, без ножек")
    Item.objects.filter(pk=a.pk).update(legacy_number="114484 · 9568/ЗАК")
    [b] = self.make(reserve="Фобос (Тура) ")            # тот же партнёр с пробелом
    [c] = self.make(reserve="Копылова (8 Марта), Красноуфимск")
    [d] = self.make(reserve="Другой")
    [t] = self.make(reserve="Фобос (Тура)"); s.trash(self.director, t.pk)
    partners = self.client.get("/api/v1/reports/nomenclature/partners/").json()
    self.assertIn({"id": "Фобос (Тура)", "name": "Фобос (Тура)", "count": 2}, partners)
    q = "Фобос (Тура)|Копылова (8 Марта), Красноуфимск"
    data = self.client.get("/api/v1/reports/nomenclature/", {"partners": q}).json()
    self.assertEqual({r["number"] for r in data["rows"]}, {a.number, b.number, c.number})
    self.assertEqual([col["title"] for col in data["columns"]], ["ID", "Заказ", "Наименование изделия", "Цена", "Угол", "Накладки", "Дополнение", "Резерв", "Менеджер", "Склад", "ВАЖНО", "Дата отгр.", "Бригада"])
    row = next(r["cells"] for r in data["rows"] if r["number"] == a.number)
    self.assertEqual((row["order"], row["corner"], row["overlays"], row["extra"]), ("9568", "Правый", "венге", "без ножек"))
    self.assertEqual(row["manager"], self.manager.last_name or self.manager.username)
    self.assertEqual(row["stage"], a.get_stage_display())
    self.assertEqual((row["price"], row["important"], row["ship_date"], row["team"]), ("", "", "", ""))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `... manage.py test app_reports`
Expected: ImportError на `split_extra` / 404 на `nomenclature`.

- [ ] **Step 3: Implement `split_extra`, `order_numbers`, `manager_name` in `rows.py`**

`Дополнение` = `sewing(item)` и остаток `split_extra`, непустые через `"; "`.

- [ ] **Step 4: Implement `partners_list`, `nomenclature`, регистрацию и эндпоинт**

`base()` дополнить `select_related("manager")` только в этом отчёте (через `.select_related` поверх). Фильтр партнёров — в Python по `i.reserve.strip()`. Сортировка `by_reserve_then_title`. `row.group = f"{резерв}: N шт."` — для экрана. Отчёт ставить в `REPORTS` сразу после `reserved`. URL `reports/nomenclature/partners/` — до `reports/<slug:kind>/`. В `PARAMS` во `views.py` добавить `OpenApiParameter("partners", str, description="партнёры через |")`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `... manage.py test app_reports`
Expected: OK, все тесты.

- [ ] **Step 6: Commit** (только с согласия пользователя)

```bash
git add src/app_reports/rows.py src/app_reports/reports.py src/app_reports/views.py src/app_reports/urls.py src/app_reports/tests.py
git commit -m "feat(reports): выгрузка для номенклатурного плана"
```

### Task 2: Голый xlsx и имя файла с фамилией менеджера (бэк)

**Files:**
- Modify: `millarym-back/src/app_reports/reports.py` (`Result.plain: bool = False`; `nomenclature` ставит `plain=True`)
- Modify: `millarym-back/src/app_reports/excel.py` (`build_xlsx`)
- Modify: `millarym-back/src/app_reports/views.py` (`run` добавляет `_user`)
- Test: `millarym-back/src/app_reports/tests.py`

**Interfaces:**
- Consumes: `nomenclature`, `PARTNER_SEP` из Task 1.
- Produces: `Result.plain`; `run(kind, params, user)` кладёт в словарь `"_user": manager_name`-подобное значение `user.last_name.strip() or user.username`.

- [ ] **Step 1: Write the failing test**

```python
# в импорты: from urllib.parse import unquote
def test_nomenclature_xlsx_is_plain(self):
    [a] = self.make(reserve="Фобос (Тура)")
    resp = self.client.get("/api/v1/reports/nomenclature/xlsx/", {"partners": "Фобос (Тура)"})
    ws = load_workbook(BytesIO(resp.content)).active
    self.assertEqual(ws["A1"].value, "ID")
    self.assertEqual(ws["M1"].value, "Бригада")
    self.assertEqual(str(ws["A2"].value), a.number)
    self.assertEqual(ws.max_row, 2)                 # ни групп, ни шапки
    self.assertEqual(ws.merged_cells.ranges, set())
    name = self.master.last_name or self.master.username
    self.assertIn(f"Номенклатура {name}", unquote(resp["Content-Disposition"]))
    old = load_workbook(BytesIO(self.client.get("/api/v1/reports/revision/xlsx/").content)).active
    self.assertEqual(old["B1"].value, "Ревизия: все изделия")   # оформление прочих не тронуто
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL, `A1` пусто (там логотип).

- [ ] **Step 3: Implement**

В `build_xlsx` при `result.plain`: заголовки в строке 1 (жирные, без заливки можно оставить ту же), строки с 2, без логотипа, B1–B4, групп и фото; автофильтр по таблице и закрепление строки 1. Номер (`ID`) — числом, если цифры, как сейчас для `kind="number"` (колонку `ID` объявить `kind="number"`). `ReportView` и `ReportXlsxView` передают `request.user` в `run`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `... manage.py test app_reports`
Expected: OK.

- [ ] **Step 5: Commit** (только с согласия пользователя)

### Task 3: Выбор партнёров на экране отчётов (фронт)

**Files:**
- Modify: `millarym-front/src/pages/reports/ui/model-picker.component.ts`
- Modify: `millarym-front/src/pages/reports/ui/reports.page.ts`, `reports.page.html`
- Modify: `millarym-front/src/entities/report/api/report.api.ts`, `model/report.types.ts`

**Interfaces:**
- Consumes: `GET /reports/nomenclature/partners/` → `ModelCount[]`, параметр `partners` через `|`.
- Produces:
  - `ModelCount.id: number | string` (было `number | 'custom'`).
  - `ModelPickerComponent` входы `allLabel = input('Все модели')`, `searchLabel = input('Найти модель')`, `pickedLabel = input('Выбрано моделей')`, `emptyLabel = input('Моделей нет')`; для свободных остатков поведение и тексты не меняются.
  - `ReportApi.nomenclaturePartners(): Observable<ModelCount[]>`.
  - В `reports.page.ts`: `partners` signal, `selectedPartners` computed (split по `|`), `setPartners(ids)` (join `|`), загрузка списка при `kind() === 'nomenclature'`.

- [ ] **Step 1: Обобщить подписи `ModelPickerComponent` и тип `ModelCount.id`**

- [ ] **Step 2: Добавить `@case ('partners')` в `reports.page.html`** с подписями «Все партнёры» / «Найти партнёра» / «Выбрано партнёров» / «Партнёров нет», `showCounts` = true.

- [ ] **Step 3: Проверить сборку**

Run: `cd millarym-front && npx ng build`
Expected: сборка без ошибок.

- [ ] **Step 4: Проверить в браузере**

Открыть «Отчёты» → «Для номенклатурного плана»: без партнёров таблицы нет; отметить двух партнёров (один с запятой в резерве) — строки обоих; «Скачать» — файл `Номенклатура <фамилия> <дата>.xlsx`, A1 = `ID`. «Свободные остатки» — выбор моделей выглядит и работает как раньше.

- [ ] **Step 5: Commit** (только с согласия пользователя)
