"""Helpers para processamento de imagem (HEIC, normalização para Gemini)."""
from __future__ import annotations

import io
from typing import Final

from PIL import Image, UnidentifiedImageError

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

MAX_DIMENSION: Final = 1600
JPEG_QUALITY: Final = 85
SUPPORTED_MIME = {"image/jpeg", "image/png", "image/webp"}
HEIC_MIME = {"image/heic", "image/heif"}


def normalize_image_for_gemini(
    img_bytes: bytes,
    filename: str = "",
) -> tuple[bytes, str]:
    """Garante que a imagem está em JPEG e com tamanho razoável.

    Returns:
        (bytes_jpeg, mime_type). Levanta UnidentifiedImageError se inválida.
    """
    try:
        img = Image.open(io.BytesIO(img_bytes))
    except UnidentifiedImageError as exc:
        raise UnidentifiedImageError(f"Formato não suportado: {filename or '?'}") from exc

    if img.mode in ("RGBA", "P", "LA") or img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > MAX_DIMENSION:
        if w >= h:
            new_w = MAX_DIMENSION
            new_h = int(h * MAX_DIMENSION / w)
        else:
            new_h = MAX_DIMENSION
            new_w = int(w * MAX_DIMENSION / h)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), "image/jpeg"


def detect_mime_from_filename(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "heic": "image/heic",
        "heif": "image/heif",
    }.get(ext, "image/jpeg")
