import re
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

FULL_SIZE = 1600
THUMB_SIZE = 300


def _webp(img: Image.Image, size: int, quality: int) -> ContentFile:
    copy = img.copy()
    copy.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    copy.save(buf, "WEBP", quality=quality, method=6)
    return ContentFile(buf.getvalue())


def shrink(file) -> tuple[ContentFile, ContentFile]:
    file.seek(0)
    img = ImageOps.exif_transpose(Image.open(file))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return _webp(img, FULL_SIZE, 82), _webp(img, THUMB_SIZE, 78)


def new_name() -> str:
    return f"{uuid.uuid4().hex}.webp"


def jpeg_bytes(path: str, quality: int = 90) -> bytes:
    """Фото для партнёров: в справочнике оно хранится в WebP, а пересылают обычно JPEG."""
    with Image.open(path) as src:
        img = src.convert("RGB")
        buf = BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def jpeg_url(kind: str, obj) -> str | None:
    """Адрес, по которому фото отдаётся в JPEG; имя файла — название записи, чтобы «Сохранить как» дало «Manila 01.jpg»."""
    if not obj.photo:
        return None
    from urllib.parse import quote

    name = re.sub(r'[\\/:*?"<>|]+', "-", obj.name).strip() or "photo"
    return f"/api/v1/{kind}/{obj.pk}/jpeg/{quote(name)}.jpg"
