"""Резервные копии на диске сервера.

Копии делает и восстанавливает служба копий (контейнер backup, deploy/backup.sh). Приложение только читает
папку копий и ставит службе задания файлами в BACKUP_ROOT/.control — папка общая у двух контейнеров.
"""

import fcntl
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

log = logging.getLogger(__name__)

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}(\d{2})?$")
DB_FILE = re.compile(r"^db_(\d{4}-\d{2}-\d{2}_\d{4}(?:\d{2})?)\.dump$")
CONFIRM_WORD = "ВОССТАНОВИТЬ"
MAINTENANCE_TEXT = "Идёт восстановление базы из резервной копии. Подождите пару минут — страница обновится сама."
HEARTBEAT_STALE = timedelta(minutes=2)
COPY_STALE = timedelta(hours=26)
SAFE_BY = re.compile(r"[^\w .\-]", re.UNICODE)
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
KEEP_RANGE = (1, 90)


def root() -> Path:
    return Path(settings.BACKUP_ROOT)


def control() -> Path:
    return root() / ".control"


def stamp_time(stamp: str) -> datetime:
    fmt = "%Y-%m-%d_%H%M%S" if len(stamp) == 17 else "%Y-%m-%d_%H%M"
    return timezone.make_aware(datetime.strptime(stamp, fmt))


def file_for(stamp: str, part: str) -> Path | None:
    if not STAMP.match(stamp or "") or part not in ("db", "media"):
        return None
    path = root() / (f"db_{stamp}.dump" if part == "db" else f"media_{stamp}.tar.gz")
    return path if path.is_file() else None


def copies() -> list[dict]:
    out = []
    for path in root().glob("db_*.dump"):
        m = DB_FILE.match(path.name)
        if not m:
            continue
        stamp = m.group(1)
        media = root() / f"media_{stamp}.tar.gz"
        note = root() / f"note_{stamp}.txt"
        out.append(
            {
                "stamp": stamp,
                "at": stamp_time(stamp),
                "db_size": path.stat().st_size,
                "media_size": media.stat().st_size if media.is_file() else None,
                "note": note.read_text(encoding="utf-8").strip() if note.is_file() else "По расписанию",
            }
        )
    return sorted(out, key=lambda c: c["at"], reverse=True)


def _read_kv(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return {}
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def tasks() -> list[dict[str, str]]:
    folder = control() / "queue"
    return [_read_kv(p) for p in sorted(folder.glob("*.task"))] if folder.is_dir() else []


def state() -> dict[str, str]:
    data = _read_kv(control() / "status")
    return {"state": data.get("state") or "idle", "text": data.get("text", ""), "since": data.get("since", "")}


def alive() -> bool:
    beat = control() / "heartbeat"
    if not beat.is_file():
        return False
    return time.time() - beat.stat().st_mtime < HEARTBEAT_STALE.total_seconds()


def busy() -> bool:
    return state()["state"] != "idle" or bool(tasks())


def history(limit: int = 30) -> list[dict]:
    path = root() / "history.log"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        parts = (line.split("\t") + [""] * 6)[:6]
        at, action, result, stamp, by, text = parts
        rows.append({"at": at, "action": action, "ok": result == "ok", "stamp": stamp, "by": by, "text": text})
    return rows[::-1]


def alerts(found: list[dict] | None = None) -> list[str]:
    out = []
    if not alive():
        out.append("Служба копий не отвечает: новые копии не делаются. Проверьте контейнер backup на сервере.")
    found = copies() if found is None else found
    if not found:
        out.append("Копий пока нет.")
    elif timezone.now() - found[0]["at"] > COPY_STALE:
        out.append(f"Последняя копия — {timezone.localtime(found[0]['at']):%d.%m.%y %H:%M}, больше суток назад.")
    last = next((h for h in history() if h["action"] == "backup"), None)
    if last and not last["ok"]:
        out.append(f"Последняя копия не удалась ({last['at']}): {last['text'] or 'ошибка'}.")
    error = control() / "migrate_error"
    if error.is_file():
        out.append(f"После восстановления не обновилась структура базы: {error.read_text(encoding='utf-8')[:300]}")
    return out


def safe(text: str, limit: int = 60) -> str:
    return SAFE_BY.sub("", text)[:limit]


def enqueue(action: str, by: str, stamp: str = "", **extra: str) -> None:
    folder = control() / "queue"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns()}.task"
    part = folder / f"{name}.part"
    lines = {"action": action, "stamp": stamp, "by": safe(by), **extra}
    part.write_text("".join(f"{k}={v}\n" for k, v in lines.items()), encoding="utf-8")
    part.rename(folder / name)


def schedule() -> dict:
    """Время ночной копии и срок хранения: поменяли на странице — лежат в .control/settings, иначе из окружения."""
    data = _read_kv(control() / "settings")
    at = data.get("at", "")
    keep = data.get("keep", "")
    return {
        "at": at if TIME.match(at) else settings.BACKUP_AT,
        "keep_days": int(keep) if keep.isdigit() else settings.BACKUP_KEEP_DAYS,
    }


def save_schedule(at: str, keep_days: int) -> None:
    folder = control()
    part = folder / "settings.part"
    part.write_text(f"at={at}\nkeep={keep_days}\n", encoding="utf-8")
    part.rename(folder / "settings")


def receive(upload, name: str) -> str:
    """Загруженный файл — в .control/incoming; проверит и переложит к копиям служба копий."""
    folder = control() / "incoming"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{time.time_ns()}_{name}"
    with open(target.with_suffix(target.suffix + ".part"), "wb") as out:
        for chunk in upload.chunks():
            out.write(chunk)
    target.with_suffix(target.suffix + ".part").rename(target)
    return target.name


def in_maintenance() -> bool:
    return (control() / "maintenance").exists()


def maintenance_text() -> str:
    return state()["text"] or MAINTENANCE_TEXT


def needs_migrate() -> bool:
    return (control() / "migrate").exists()


def finish_restore() -> None:
    """Служба восстановила базу из копии — догоняем структуру до текущей версии (копия могла быть старше) и открываем доступ.

    Делает первый пришедший запрос; остальные ждут за заглушкой. Блокировка — чтобы migrate не запустили два воркера.
    """
    folder = control()
    with open(folder / "migrate.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if not needs_migrate():
            return
        (folder / "migrate_error").unlink(missing_ok=True)
        try:
            call_command("migrate", interactive=False, verbosity=0)
        except Exception as exc:  # доступ всё равно открываем, ошибку видно на странице копий
            log.exception("migrate после восстановления")
            (folder / "migrate_error").write_text(str(exc), encoding="utf-8")
        (folder / "migrate").unlink(missing_ok=True)
        (folder / "maintenance").unlink(missing_ok=True)
