"""Gera os ícones PNG do ThéoOS a partir do SVG.

Rode uma vez: python scripts/gen_pwa_icons.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow não está instalado. pip install pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "static" / "icons"
ICONS.mkdir(parents=True, exist_ok=True)

BRAND_BG = (12, 14, 18)
BRAND_TEAL = (45, 212, 191)
WHITE = (236, 240, 245)


def _draw_logo(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), BRAND_BG)
    d = ImageDraw.Draw(img)
    pad = size // 12
    stroke = max(2, size // 24)
    # círculo
    bbox = (pad, pad, size - pad, size - pad)
    d.ellipse(bbox, outline=BRAND_TEAL, width=stroke)
    # ponteiro do relógio (linha de cima + diagonal)
    cx = cy = size // 2
    r = (size - 2 * pad - stroke) // 2
    # vertical
    d.line([(cx, cy - r), (cx, cy)], fill=BRAND_TEAL, width=stroke)
    # diagonal
    d.line([(cx, cy), (cx + int(r * 0.71), cy + int(r * 0.71))], fill=BRAND_TEAL, width=stroke)
    return img


def _make_maskable(size: int) -> Image.Image:
    """Para maskable, o conteúdo importante fica no inner 80% (safe zone)."""
    img = _draw_logo(size)
    # maskable precisa de fundo sólido até as bordas (sem cantos arredondados)
    # já tem, e o logo está centralizado no inner 80% ✓
    return img


def main() -> int:
    for size, name in (
        (192, "icon-192.png"),
        (512, "icon-512.png"),
        (180, "apple-touch-icon.png"),  # iOS
    ):
        path = ICONS / name
        _make_maskable(size).save(path, "PNG", optimize=True)
        print(f"OK {name} ({size}x{size})")

    # Favicon PNG 32x32 para browsers que pedem
    fav32 = ICONS / "favicon-32.png"
    _draw_logo(32).save(fav32, "PNG", optimize=True)
    print("OK favicon-32.png (32x32)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
