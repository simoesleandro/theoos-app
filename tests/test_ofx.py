"""Testes do gerador de OFX."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from theoos.ofx import build_ofx, _format_amount, _format_date  # noqa: E402


def test_format_date():
    dt = datetime(2026, 6, 15, 14, 30, 45)
    assert _format_date(dt) == "20260615143045"


def test_format_amount_positive():
    assert _format_amount(123.45) == "123.45"


def test_format_amount_negative():
    assert _format_amount(-50.0) == "-50.00"


def test_build_ofx_minimal():
    out = build_ofx([])
    assert out.startswith("OFXHEADER:100")
    assert "<OFX>" in out
    assert "<STMTRS>" in out
    assert "<CURDEF>BRL</CURDEF>" in out
    assert "BANKACCTFROM" in out


def test_build_ofx_com_transacoes():
    txs = [
        {
            "data": datetime(2026, 6, 10, 12, 0, 0),
            "valor": -150.0,
            "name": "Supermercado",
            "memo": "Compras do mes",
        },
        {
            "data": datetime(2026, 6, 15, 9, 30, 0),
            "valor": 3000.0,
            "name": "Salario",
        },
    ]
    out = build_ofx(txs, ledger_balance=2850.0)
    assert "OFXHEADER:100" in out
    assert "<TRNTYPE>DEBIT</TRNTYPE>" in out
    assert "<TRNTYPE>CREDIT</TRNTYPE>" in out
    assert "<TRNAMT>-150.00</TRNAMT>" in out
    assert "<TRNAMT>3000.00</TRNAMT>" in out
    assert "<BALAMT>2850.00</BALAMT>" in out
    assert "Supermercado" in out
    assert "<MEMO>Compras do mes</MEMO>" in out


def test_build_ofx_xml_escape():
    txs = [{"data": datetime(2026, 6, 1, 10, 0, 0), "valor": -10.0, "name": "A&B<C>"}]
    out = build_ofx(txs)
    assert "A&amp;B&lt;C&gt;" in out
