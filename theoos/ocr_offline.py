"""OCR offline via Tesseract (fallback quando Gemini Vision nao disponivel).

Tesseract precisa estar instalado no sistema:
    Windows: choco install tesseract  (ou baixar de https://github.com/UB-Mannheim/tesseract/wiki)
    Linux:   apt install tesseract-ocr tesseract-ocr-por
    macOS:   brew install tesseract tesseract-lang

Pacote Python:
    pip install pytesseract

Se Tesseract nao estiver instalado, parse_receipt_offline() levanta um
TesseractNotFoundError. A chamada em upload_nota trata o erro graciosamente
(cai de volta para entrada manual ou mensagem amigavel).
"""
from __future__ import annotations

import io
import json
import logging
import re
from typing import Optional

from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

try:
    import pytesseract  # type: ignore

    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False
    pytesseract = None  # type: ignore


class TesseractNotFoundError(RuntimeError):
    """Tesseract nao instalado ou nao encontrado no PATH."""


class OCRError(RuntimeError):
    """Erro genérico de OCR."""


def is_available() -> bool:
    """Retorna True se Tesseract esta instalado e acessivel."""
    if not _HAS_TESSERACT:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Melhorias comuns para cupons: grayscale + threshold."""
    if img.mode != "L":
        img = img.convert("L")
    return img.point(lambda p: 0 if p < 140 else 255)


def _find_total(text: str) -> Optional[float]:
    """Tenta extrair o valor total do cupom a partir do texto OCR."""
    patterns = [
        r"(?:total|valor\s+a\s+pagar|total\s+a\s+pagar)\s*[:\-]?\s*r?\$?\s*(\d{1,5}[.,]\d{2})",
        r"r\$\s*(\d{1,5}[.,]\d{2})\s*$",
        r"(\d{1,5}[.,]\d{2})",
    ]
    candidates: list[float] = []
    for pat in patterns[:2]:
        for m in re.finditer(pat, text, re.IGNORECASE | re.MULTILINE):
            try:
                v = float(m.group(1).replace(",", "."))
                if v > 0:
                    candidates.append(v)
            except ValueError:
                pass
    if candidates:
        return max(candidates)
    m = re.search(r"(\d{1,5}[.,]\d{2})", text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None
    return None


def _find_mercado(text: str) -> Optional[str]:
    """Primeira linha não-vazia razoável como nome de mercado."""
    for line in text.splitlines():
        s = line.strip()
        if 3 <= len(s) <= 40 and not re.search(r"^\d", s) and "cpf" not in s.lower():
            return s
    return None


def parse_receipt_offline(image_bytes: bytes) -> dict:
    """OCR Tesseract em uma imagem de cupom.

    Returns dict no mesmo formato que Gemini:
        {"mercado": str, "data": str, "total_nota": float,
         "itens": [], "ids_comprados": []}

    OBS: extração de itens via Tesseract é limitada; retorna [] (sem itens).
    O usuário completa manualmente no editor.

    Levanta:
        TesseractNotFoundError se Tesseract não estiver instalado
        OCRError para outros erros (imagem inválida, OCR falhou)
    """
    if not _HAS_TESSERACT:
        raise TesseractNotFoundError("pytesseract não está instalado (pip install pytesseract)")
    try:
        version = pytesseract.get_tesseract_version()
    except Exception as e:
        raise TesseractNotFoundError(f"Tesseract não encontrado no PATH: {e}")
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "L":
            img = img.convert("L")
        img = _preprocess_for_ocr(img)
        text = pytesseract.image_to_string(img, lang="por+eng")
    except UnidentifiedImageError as e:
        raise OCRError(f"Formato de imagem não suportado: {e}")
    except Exception as e:
        raise OCRError(f"Erro de OCR: {e}")

    log.debug("OCR offline extraiu %d caracteres", len(text))
    return {
        "mercado": _find_mercado(text) or "Desconhecido",
        "data": "",  # data é difícil de extrair com regex
        "total_nota": _find_total(text) or 0.0,
        "itens": [],
        "ids_comprados": [],
        "raw_text": text,
    }
