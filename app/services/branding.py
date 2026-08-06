from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import BASE_DIR

BRANDING_DIR = BASE_DIR / "data" / "branding"
ALLOWED_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ROLES = {"horizontal", "vertical", "icon"}


def safe_branding_path(filename: str) -> Path | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,80}", filename or ""):
        return None
    path = BRANDING_DIR / filename
    return path if path.parent == BRANDING_DIR else None


def remove_logo(role: str) -> None:
    if role not in ROLES:
        return
    BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    for path in BRANDING_DIR.glob(f"{role}.*"):
        path.unlink(missing_ok=True)
    (BRANDING_DIR / f"{role}-preview.png").unlink(missing_ok=True)
    if role == "icon":
        for name in ("pwa-192.png", "pwa-512.png", "favicon.png"):
            (BRANDING_DIR / name).unlink(missing_ok=True)


def _validate_svg(data: bytes) -> bytes:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("O arquivo SVG não está em UTF-8.") from exc
    lowered = text.lower()
    forbidden = ("<!doctype", "<!entity", "<script", "<foreignobject", "javascript:")
    if "<svg" not in lowered or any(item in lowered for item in forbidden):
        raise ValueError("O SVG contém conteúdo não permitido.")
    if re.search(r"\son[a-z]+\s*=", lowered) or re.search(r"(?:href|src)\s*=\s*['\"]\s*(?:https?:|//|data:)", lowered):
        raise ValueError("O SVG contém referências externas ou eventos não permitidos.")
    return text.encode("utf-8")


def _open_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("A imagem enviada não pôde ser lida.") from exc
    if image.width < 16 or image.height < 16 or image.width * image.height > 40_000_000:
        raise ValueError("A imagem possui dimensões inválidas ou excessivas.")
    return ImageOps.exif_transpose(image).convert("RGBA")


def _write_png(image: Image.Image, path: Path, size: tuple[int, int], contain: bool = True) -> None:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    working = image.copy()
    if contain:
        working.thumbnail(size, Image.Resampling.LANCZOS)
        canvas.alpha_composite(working, ((size[0] - working.width) // 2, (size[1] - working.height) // 2))
    else:
        canvas = ImageOps.fit(working, size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    canvas.save(path, "PNG", optimize=True)


def save_logo(role: str, filename: str, data: bytes, preview_data: bytes | None = None) -> str:
    if role not in ROLES:
        raise ValueError("Tipo de logo inválido.")
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("A logo deve ter no máximo 8 MB.")
    extension = Path(filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Use SVG, PNG, JPG ou WebP.")
    remove_logo(role)
    BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{role}{extension}"
    if extension == ".svg":
        data = _validate_svg(data)
    else:
        _open_image(data)
    (BRANDING_DIR / stored_name).write_bytes(data)

    preview: Image.Image | None = None
    if preview_data:
        preview = _open_image(preview_data)
    elif extension != ".svg":
        preview = _open_image(data)
    if preview:
        preview_size = (1200, 360) if role == "horizontal" else ((520, 760) if role == "vertical" else (512, 512))
        _write_png(preview, BRANDING_DIR / f"{role}-preview.png", preview_size)
        if role == "icon":
            _write_png(preview, BRANDING_DIR / "pwa-512.png", (512, 512))
            _write_png(preview, BRANDING_DIR / "pwa-192.png", (192, 192))
            _write_png(preview, BRANDING_DIR / "favicon.png", (64, 64))
    return stored_name
