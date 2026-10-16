import re
import zipfile
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from app_catalog.models import Fabric

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def fabric_name(filename: str) -> str:
    return re.sub(r"\s+", " ", Path(filename).stem.replace("_", " ")).strip()


def read_images(source: Path) -> list[tuple[str, bytes]]:
    """Пары (имя файла, содержимое) из папки (со вложенными) или zip-архива."""
    if source.is_dir():
        files = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT)
        return [(p.name, p.read_bytes()) for p in files if not p.name.startswith(".")]
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            result = []
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                raw_name = info.filename
                if not info.flag_bits & 0x800:
                    # архивы из Проводника Windows хранят русские имена в cp866
                    try:
                        raw_name = raw_name.encode("cp437").decode("cp866")
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        pass
                name = Path(raw_name).name
                if info.is_dir() or name.startswith(".") or "__MACOSX" in raw_name:
                    continue
                if Path(name).suffix.lower() in IMAGE_EXT:
                    result.append((name, archive.read(info)))
            return result
    raise CommandError("Укажите папку с картинками или zip-архив.")


def is_image(content: bytes) -> bool:
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
        return True
    except (UnidentifiedImageError, OSError, SyntaxError):
        return False


class Command(BaseCommand):
    help = "Загрузить фото тканей: название ткани — имя файла без расширения. Новые ткани заводятся."

    def add_arguments(self, parser):
        parser.add_argument("path", help="папка с картинками или zip-архив")
        parser.add_argument("--replace", action="store_true", help="заменять фото, если у ткани оно уже есть")
        parser.add_argument("--no-create", action="store_true", help="не заводить новые ткани, только ставить фото")
        parser.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")

    def handle(self, *args, path, replace, no_create, dry_run, **options):
        source = Path(path)
        if not source.exists():
            raise CommandError(f"Нет такого пути: {source}.")
        images = read_images(source)
        if not images:
            raise CommandError("Картинок не найдено (jpg, png, webp и т. п.).")

        existing = {f.name.lower(): f for f in Fabric.objects.all()}
        seen: set[str] = set()
        created = photos = kept = skipped = 0
        problems: list[str] = []

        for filename, content in images:
            name = fabric_name(filename)
            key = name.lower()
            if not name:
                problems.append(f"{filename}: пустое имя")
                continue
            if key in seen:
                problems.append(f"{filename}: ткань «{name}» уже встречалась в загрузке — пропущен")
                continue
            seen.add(key)
            if len(name) > Fabric._meta.get_field("name").max_length:
                problems.append(f"{filename}: слишком длинное название")
                continue
            if not is_image(content):
                problems.append(f"{filename}: не картинка или файл повреждён")
                continue

            fabric = existing.get(key)
            if fabric is None and no_create:
                skipped += 1
                continue
            if fabric is not None and fabric.photo and not replace:
                kept += 1
                continue

            if fabric is None:
                created += 1
            photos += 1
            if dry_run:
                continue
            with transaction.atomic():
                if fabric is None:
                    fabric = Fabric(name=name)
                fabric.photo = SimpleUploadedFile(filename, content)
                fabric.save()
            existing[key] = fabric

        prefix = "Проверка (ничего не сохранено). " if dry_run else ""
        self.stdout.write(
            f"{prefix}Картинок: {len(images)}. Фото поставлено: {photos}, из них новых тканей: {created}. "
            f"Фото уже было (без --replace не трогаем): {kept}."
            + (f" Без ткани в справочнике пропущено: {skipped}." if no_create else "")
        )
        if problems:
            self.stdout.write(f"Не загружено: {len(problems)}")
            for line in problems:
                self.stdout.write(f"  {line}")
