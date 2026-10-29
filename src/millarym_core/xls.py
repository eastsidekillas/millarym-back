"""Выгрузки в Excel 97–2003 (.xls).

На заводе стоит старый Excel: файлы .xlsx он открывает через пакет совместимости, и при сохранении данные теряются.
Файл собираем как обычно (openpyxl, .xlsx), а в .xls переводит LibreOffice — сохраняются объединения, картинки,
фильтр и списки выбора. Без LibreOffice (разработка, тесты) — отдаём .xlsx как есть.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponse

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_TYPE = "application/vnd.ms-excel"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class ConvertError(Exception):
    pass


def soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def legacy_enabled() -> bool:
    return settings.EXCEL_FORMAT == "xls" and soffice() is not None


def _convert(data: bytes, src_ext: str, filter_: str, dst_ext: str) -> bytes:
    exe = soffice()
    if exe is None:
        raise ConvertError("LibreOffice не установлен")
    # профиль свой у каждого процесса gunicorn: один профиль двумя запусками сразу LibreOffice не открывает,
    # а процесс обрабатывает запросы по одному. Постоянный профиль — второй и следующие запуски быстрее
    profile = Path(tempfile.gettempdir()) / f"lo-profile-{os.getpid()}"
    with tempfile.TemporaryDirectory(prefix="xls-") as tmp:
        src = Path(tmp) / f"file.{src_ext}"
        src.write_bytes(data)
        try:
            subprocess.run(
                [exe, "--headless", "--norestore", f"-env:UserInstallation={profile.as_uri()}",
                 "--convert-to", filter_, "--outdir", tmp, str(src)],
                check=True, capture_output=True, timeout=120,
                env={**os.environ, "HOME": tmp},
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise ConvertError(str(exc)) from exc
        out = Path(tmp) / f"file.{dst_ext}"
        if not out.exists():
            raise ConvertError("LibreOffice не создал файл")
        return out.read_bytes()


def to_xls(xlsx: bytes) -> bytes:
    return _convert(xlsx, "xlsx", "xls:MS Excel 97", "xls")


def to_xlsx(xls: bytes) -> bytes:
    """Загрузка справочников: файл, сохранённый в старом Excel, читаем так же, как .xlsx."""
    return _convert(xls, "xls", "xlsx:Calc MS Excel 2007 XML", "xlsx")


def is_xls(data: bytes) -> bool:
    return data[:8] == OLE_MAGIC


def excel_response(xlsx: bytes, name: str, fallback: str) -> HttpResponse:
    """name — имя файла без расширения (кириллица), fallback — латиницей для старых браузеров."""
    content, ext, kind = xlsx, "xlsx", XLSX_TYPE
    if legacy_enabled():
        try:
            content, ext, kind = to_xls(xlsx), "xls", XLS_TYPE
        except ConvertError:
            pass  # лучше .xlsx, чем ошибка вместо отчёта
    response = HttpResponse(content, content_type=kind)
    response["Content-Disposition"] = f"attachment; filename={fallback}.{ext}; filename*=UTF-8''{quote(f'{name}.{ext}')}"
    response["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response
