import sys
from pathlib import Path

from django.template.loader import render_to_string

from app_production.errors import ActionError

ASSETS = Path(__file__).resolve().parent / "assets"


def _find_homebrew_libs() -> None:
    # macOS (SIP) стирает DYLD_FALLBACK_LIBRARY_PATH при запуске через poetry и IDE,
    # а без неё dlopen не заглядывает в /opt/homebrew/lib, где Homebrew на Apple Silicon держит Pango.
    lib = Path("/opt/homebrew/lib")
    if sys.platform != "darwin" or not lib.is_dir():
        return
    import cffi

    original = cffi.FFI.dlopen
    if getattr(original, "homebrew", False):
        return

    def dlopen(self, name, flags=0):
        try:
            return original(self, name, flags)
        except OSError:
            if isinstance(name, str) and "/" not in name and (lib / name).exists():
                return original(self, str(lib / name), flags)
            raise

    dlopen.homebrew = True
    cffi.FFI.dlopen = dlopen


def render_pdf(template: str, context: dict) -> bytes:
    html = render_to_string(
        template, {**context, "fonts": (ASSETS / "fonts").as_uri(), "logo": (ASSETS / "logo.png").as_uri()}
    )
    _find_homebrew_libs()
    try:
        from weasyprint import HTML
    except OSError:
        raise ActionError("PDF не собрать: на сервере не найдена библиотека Pango (см. README, «Паспорт изделия»).")
    return HTML(string=html, base_url=str(ASSETS)).write_pdf()
