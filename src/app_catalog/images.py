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
