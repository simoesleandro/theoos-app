"""Testes do parser CSV de extrato bancário."""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from theoos.reconcile import (  # noqa: E402
    _detect_bank_format,
    _detect_columns,
    _looks_like_header,
    _normalize_amount,
    _normalize_date,
    match_against_financas,
    parse_bank_csv,
)


def test_normalize_amount_br():
    assert _normalize_amount("1.234,56") == 1234.56
    assert _normalize_amount("1234.56") == 1234.56
    assert _normalize_amount("R$ 1.234,56") == 1234.56
    assert _normalize_amount("-50,00") == -50.0
    assert _normalize_amount("0,99") == 0.99


def test_normalize_date_br():
    assert _normalize_date("15/06/2026") == "2026-06-15"
    assert _normalize_date("2026-06-15") == "2026-06-15"
    assert _normalize_date("15-06-2026") == "2026-06-15"
    assert _normalize_date("15.06.2026") == "2026-06-15"
    assert _normalize_date("invalido") is None
    assert _normalize_date("") is None
    assert _normalize_date("06/15/2026") == "2026-06-15"


def test_detect_columns_nubank():
    headers = ["data", "descrição", "valor", "categoria"]
    m = _detect_columns(headers)
    assert m["data"] == 0
    assert m["descricao"] == 1
    assert m["valor"] == 2


def test_detect_columns_inter():
    headers = ["Data", "Lançamento", "Valor", "Tipo"]
    m = _detect_columns(headers)
    assert m["data"] == 0
    assert m["descricao"] == 1
    assert m["valor"] == 2
    assert m["tipo"] == 3


def test_detect_bank_format():
    assert _detect_bank_format(["nuconta", "data", "valor"]) == "nubank"
    assert _detect_bank_format(["Data", "Lançamento", "Valor", "Tipo"]) in ("inter", "generico")
    assert _detect_bank_format(["itau", "data", "descricao", "valor"]) == "itau"
    assert _detect_bank_format(["data", "descricao", "valor"]) == "generico"


def test_looks_like_header():
    assert _looks_like_header(["data", "valor", "descricao"]) is True
    assert _looks_like_header(["15/06/2026", "Supermercado", "150,00"]) is False


def test_parse_csv_sem_cabecalho():
    csv = (
        "15/06/2026;Compra no mercado;150,00\n"
        "16/06/2026;Salario;3000,00\n"
    ).encode("latin-1")
    lancs, meta = parse_bank_csv(csv, encoding="latin-1")
    assert meta["validos"] == 2
    assert lancs[0]["data"] == "2026-06-15"
    assert lancs[0]["descricao"] == "Compra no mercado"
    assert lancs[0]["valor"] == 150.0
    assert lancs[1]["valor"] == 3000.0


def test_parse_csv_com_cabecalho():
    csv = (
        "data,descricao,valor,tipo\n"
        "2026-06-15,Compra no mercado,150.00,debito\n"
        "2026-06-16,Salario,3000.00,credito\n"
    ).encode("utf-8")
    lancs, meta = parse_bank_csv(csv)
    assert meta["formato"] == "generico"
    assert meta["validos"] == 2
    assert lancs[0]["_negativo"] is False
    assert lancs[1]["_negativo"] is True
    assert lancs[1]["tipo"] == "credito"


def test_parse_csv_negativo_sinal_mais():
    csv = "data,descricao,valor\n15/06/2026,Estorno,-50,00\n".encode("latin-1")
    lancs, _ = parse_bank_csv(csv, encoding="latin-1")
    assert lancs[0]["valor"] == 50.0
    assert lancs[0]["_negativo"] is True


def test_match_against_financas():
    from types import SimpleNamespace

    class FakeFin:
        data = datetime(2026, 6, 15, 10, 0, 0)
        valor = 150.0
        tipo = "debito"

    financas = [FakeFin()]
    class FakeQuery:
        def filter_by(self, **kw):
            return self
        def all(self):
            return financas

    class FakeModel:
        query = FakeQuery()

    lancs = [{"data": "2026-06-15", "descricao": "X", "valor": 150.0, "tipo": ""}]
    result = match_against_financas(lancs, FakeModel)
    assert result[0]["conciliado"] is True
    assert result[0]["novo"] is False
