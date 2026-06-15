"""Testes do parser de linha digitavel de boleto."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from theoos.boleto import _dv_mod10, parse_linha_digitavel  # noqa: E402


def _build_linha(fator="1000", valor="00001234"):
    banco = "237"
    moeda = "9"
    agencia = "01234"
    nosso1 = "1234567890"
    nosso2 = "0987654321"
    b1 = banco + moeda + agencia
    dv1 = _dv_mod10(b1)
    b2 = nosso1
    dv2 = _dv_mod10(b2)
    b3 = nosso2
    dv3 = _dv_mod10(b3)
    b5 = fator
    dv5 = _dv_mod10(b5)
    return (
        b1 + str(dv1) + b2 + str(dv2) + b3 + str(dv3) + "0" + b5 + str(dv5) + valor + "0"
    )


def test_parse_valido():
    linha = _build_linha()
    r = parse_linha_digitavel(linha)
    assert r["banco"] == "237"
    assert r["moeda"] == "9"
    assert r["valor"] == 12.34
    assert r["agencia"] == "01234"
    assert r["nosso_numero"] == "0987654321"
    assert r["vencimento"] == date(1997, 10, 7) + timedelta(days=1000)


def test_parse_com_espacos_e_pontos():
    linha = _build_linha()
    com_espaco = linha[:10] + " " + linha[10:21] + " " + linha[21:32] + " " + linha[32:33] + " " + linha[33:]
    r = parse_linha_digitavel(com_espaco)
    assert r["valor"] == 12.34


def test_parse_moeda_invalida():
    linha = "237" + "0" + "01234" + "5" + "1234567890" + "1" + "0987654321" + "2" + "0" + "1000" + "0" + "00001234" + "0"
    try:
        parse_linha_digitavel(linha)
        assert False, "Deveria ter levantado ValueError"
    except ValueError as e:
        assert "Moeda" in str(e) or "47" in str(e)


def test_parse_tamanho_invalido():
    try:
        parse_linha_digitavel("12345")
    except ValueError as e:
        assert "47" in str(e)


def test_fator_zero_sem_vencimento():
    linha = _build_linha(fator="0000")
    r = parse_linha_digitavel(linha)
    assert r["vencimento"] is None
    assert r["valor"] == 12.34
