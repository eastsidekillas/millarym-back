"""Разбор свободного текста старых систем: даты, названия изделий, ткани."""

import re
from datetime import date, datetime
from datetime import timezone as dt_timezone

from django.utils import timezone

NBSP = re.compile(r"&nbsp;|\xa0")
SPACES = re.compile(r"\s+")
IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|bmp)\s*$", re.IGNORECASE)
DATE = re.compile(r"(?<!\d)(\d{1,2})[.,](\d{1,2})[.,\s](\d{4}|\d{2})(?!\d)")
ORDER_REF = re.compile(r"№\s*(\d{3,5})")
EMPTY = {"", ".", "-", "—", "нет", "0", "*", "no photo", "nophoto", "no-photo"}


def clean(value) -> str:
    s = NBSP.sub(" ", str(value or ""))
    # «кровать 1600*200015,10,26» — дата приклеена к размеру
    s = re.sub(r"(\*\d{4})(?=\d{1,2}[.,]\d)", r"\1 ", s)
    return SPACES.sub(" ", s).strip()


def unix_date(value) -> date | None:
    try:
        ts = int(value or 0)
    except ValueError:
        return None
    if ts <= 0:
        return None
    return timezone.localtime(datetime.fromtimestamp(ts, tz=dt_timezone.utc)).date()


def text_date(value, default_year: int | None = None) -> date | None:
    """«15.08.17.», «19,10,26», «24.06.2021», «19.10.2026» → дата; нераспознанное — None."""
    s = clean(value)
    m = DATE.search(s)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        year += 2000 if year < 100 else 0
    else:
        m = re.search(r"(?<!\d)(\d{1,2})[.,](\d{1,2})(?![.,]?\d)", s)
        if not m or not default_year:
            return None
        day, month, year = int(m.group(1)), int(m.group(2)), default_year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def sewing_dates(comment: str) -> tuple[date | None, date | None]:
    """Комментарий «в шитье 08.10. отшит 14.10.26» → (выдано в шитьё, отшит)."""
    s = clean(comment).lower()
    ready = None
    m = re.search(r"отшит\w*\s*([\d.,\s]+)", s)
    if m:
        ready = text_date(m.group(1))
    sew = None
    m = re.search(r"в\s*шить[её]\s*([\d.,\s]+)", s)
    if m:
        anchor = ready or timezone.localdate()
        sew = text_date(m.group(1), default_year=anchor.year)
        if sew and sew > anchor:
            # «в шитье 28.12.» при «отшит 05.01.26» — прошлый год
            sew = _year_back(sew)
    return sew, ready


def _year_back(d: date) -> date | None:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return None


def only_sewing(comment: str) -> bool:
    """Комментарий — только «в шитье … отшит …», который уже разобран в даты."""
    return bool(re.fullmatch(r"\s*в\s*шить[её]\s*[\d.,\s]+отшит\w*\s*[\d.,\s]+", clean(comment).lower()))


def order_refs(name: str) -> list[int]:
    return [int(n) for n in ORDER_REF.findall(name or "")]


def fabric_key(name: str) -> str:
    """Ключ для сопоставления тканей: как у импорта фото — имя файла без расширения, «_» → пробел, без регистра."""
    s = IMAGE_EXT.sub("", clean(name))
    return SPACES.sub(" ", s.replace("_", " ")).strip().lower().replace("ё", "е")


def fabric_name(value) -> str:
    """Ткань из старого поля: имя файла или текст («. Арбен Ultra cedar») → название; пусто — ''."""
    s = IMAGE_EXT.sub("", clean(value).lstrip(".").strip())
    s = SPACES.sub(" ", s.replace("_", " ")).strip()
    return "" if s.lower() in EMPTY else s


# латиница, похожая на кириллицу: «Модерн B» в старой базе и «Модерн В» в справочнике
HOMOGLYPHS = str.maketrans("авекмнорстух", "abekmhopctyx")


def fold(s: str) -> str:
    return s.translate(HOMOGLYPHS)


def model_key(name: str) -> tuple[str, bool]:
    s = clean(name).lower().replace("ё", "е")
    four = "(4 кат.)" in s
    s = s.replace("(4 кат.)", "")
    return SPACES.sub(" ", s).strip(), four


KIND_PREFIX = re.compile(r"^(бд|диван|кресло|кровать|пуф)\b\s*", re.IGNORECASE)
QTY = re.compile(r"[-–—=]?\s*(\d+)\s*(?:шт\w*|штук\w*)\.?", re.IGNORECASE)


class ModelMatcher:
    """Находит модель справочника по началу названия из старой системы."""

    def __init__(self, models):
        self.by_key: dict[tuple[str, bool], object] = {}
        for m in models:
            key, four = model_key(m.name)
            self.by_key.setdefault((key, four), m)
        self.keys = sorted({k for k, _ in self.by_key}, key=len, reverse=True)
        self.folded = [(fold(k), k) for k in self.keys]

    def _normalize(self, name: str) -> tuple[list[tuple[str, str | None]], bool]:
        """Варианты (текст, обязательное слово в названии модели) и признак «4 кат.»."""
        s = clean(name).lower().replace("ё", "е")
        s = re.sub(r"[«»\"“”]", " ", s)
        s = re.sub(r"\(\s*(?:заказ[^)]*|№[^)]*)\)", " ", s)
        s = re.sub(r"\bзаказ\w*\s*№?\s*\d*", " ", s)
        s = ORDER_REF.sub(" ", s)
        s = DATE.sub(" ", s)
        four = bool(re.search(r"4\s*кат", s))
        s = re.sub(r"\(?\s*\d+\s*кат\.?\s*\)?", " ", s)
        s = QTY.sub(" ", s)
        s = SPACES.sub(" ", s).strip()
        kind = None
        m = KIND_PREFIX.match(s)
        if m:
            kind = m.group(1)
            s = s[m.end():]
        s = SPACES.sub(" ", re.sub(r"[^\w*\-\s]", " ", s)).strip()
        without_sofa = SPACES.sub(" ", re.sub(r"\bдиван\b", " ", s)).strip()
        if kind in ("кресло", "пуф", "кровать"):
            # «Кресло "Дубай М"» → «дубай м кресло», «Пуф Бисмарк» → «бисмарк пуф»;
            # без слова-вида не ищем, иначе «Кресло Бостон» найдёт диван «Бостон»
            variants = []
            for v in (s, without_sofa):
                words = v.split(" ")
                for n in (2, 1):
                    if len(words) >= n:
                        variants.append((" ".join(words[:n] + [kind] + words[n:]), kind))
        else:
            variants = [(s, None), (without_sofa, None)]
        return variants, four

    def match(self, name: str):
        """(модель или None, остаток текста после названия модели)."""
        variants, four = self._normalize(name)
        for v, required in variants:
            fv = fold(v)
            for fkey, key in self.folded:
                if required and required not in key.split(" "):
                    continue
                if fv == fkey or fv.startswith(fkey + " "):
                    model = self.by_key.get((key, four)) or self.by_key.get((key, False)) or self.by_key.get((key, True))
                    return model, v[len(key):].strip()
        return None, variants[0][0] if variants else ""


NOISE = re.compile(r"\b(диван|фото|проверено)\b|\*|\+|\s\d{1,2}\s\d{1,2}(?:\s\d{2,4})?\b", re.IGNORECASE)


def extra_from(rest: str) -> str:
    s = NOISE.sub(" ", " " + rest + " ")
    s = SPACES.sub(" ", s).strip(" -–—,.")
    return s[:1].upper() + s[1:] if s else ""


def custom_name_from(name: str, strip_qty: bool = False) -> str:
    s = clean(name)
    s = re.sub(r"\(\s*(?:заказ[^)]*|№[^)]*)\)", " ", s, flags=re.IGNORECASE)
    s = ORDER_REF.sub(" ", s)
    s = DATE.sub(" ", s)
    s = re.sub(r"\bПРОВЕРЕНО\b|\+", " ", s)
    if strip_qty:
        s = QTY.sub(" ", s)
    return SPACES.sub(" ", s).strip(" -–—,.")[:200]


def quantity(name: str) -> int:
    m = QTY.search(clean(name))
    return max(1, min(int(m.group(1)), 20)) if m else 1
