"""Testes do OCR offline (Tesseract fallback)."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_is_available_sem_tesseract():
    from theoos import ocr_offline
    with patch.object(ocr_offline, "_HAS_TESSERACT", False):
        assert ocr_offline.is_available() is False


def test_parse_receipt_offline_sem_pytesseract():
    from theoos.ocr_offline import TesseractNotFoundError, parse_receipt_offline
    with patch.dict(sys.modules, {"pytesseract": None}):
        with patch("theoos.ocr_offline._HAS_TESSERACT", False):
            try:
                parse_receipt_offline(b"fake")
                assert False, "Deveria levantar TesseractNotFoundError"
            except TesseractNotFoundError:
                pass


def test_parse_receipt_offline_sem_binario():
    from theoos.ocr_offline import TesseractNotFoundError, is_available, parse_receipt_offline
    fake_pytesseract = MagicMock()
    fake_pytesseract.get_tesseract_version.side_effect = Exception("not found")
    with patch.dict(sys.modules, {"pytesseract": fake_pytesseract}):
        with patch("theoos.ocr_offline._HAS_TESSERACT", True):
            assert is_available() is False
            try:
                parse_receipt_offline(b"fake")
                assert False, "Deveria levantar TesseractNotFoundError"
            except TesseractNotFoundError:
                pass


def test_find_total():
    from theoos.ocr_offline import _find_total
    text = "Supermercado\nTotal: R$ 123,45\nObrigado"
    assert _find_total(text) == 123.45


def test_find_total_fallback():
    from theoos.ocr_offline import _find_total
    text = "Sem total claro aqui\n 50,00 visivel"
    assert _find_total(text) == 50.0


def test_find_mercado():
    from theoos.ocr_offline import _find_mercado
    text = "SUPERMERCADO BOM PRECO LTDA\nCNPJ: 12.345.678/0001-90\nTotal: 100,00"
    m = _find_mercado(text)
    assert m is not None
    assert "BOM" in m.upper() or "SUPER" in m.upper()
