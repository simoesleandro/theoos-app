"""Parser de linha digitável de boletos (padrão Febraban 47/48 dígitos).

A linha digitável tem 47 dígitos (boletos bancários) ou 48 (contas concessionárias).
Esta implementação cobre boletos bancários (47 dígitos), que é o caso comum
para contas a pagar familiares (luz, água, cartão de crédito etc).

Retorna um dict com:
    banco: str (3 dígitos)
    moeda: str ("9" = Real)
    valor: float (em R$)
    vencimento: date | None (calculado a partir do fator)
    agencia: str
    nosso_numero: str
    raw: str (linha normalizada sem espaços)
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

_DIGIT_RE = re.compile(r"\D+")
_FEBRABAN_EPOCH = date(1997, 10, 7)
_MAX_FATOR = 9999


def _only_digits(s: str) -> str:
    return _DIGIT_RE.sub("", s or "")


def _dv_mod10(num: str) -> int:
    """Dígito verificador módulo 10 (peso 2 a 9 da direita para a esquerda)."""
    peso = 2
    soma = 0
    for d in reversed(num):
        v = int(d) * peso
        soma += v if v < 10 else (v - 9)
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 10
    return 0 if resto == 0 else 10 - resto


def _check_block(num: str, dv: int) -> bool:
    return _dv_mod10(num) == dv


def _parse_field5(block: str) -> tuple[Optional[date], float]:
    """Field 5 (positions 34-47, 14 digits): fator de vencimento + valor + zero.

    4 dígitos fator + 1 DV + 8 dígitos valor (com 2 casas decimais implícitas) + 1 zero.
    """
    if len(block) != 14:
        return None, 0.0
    fator_str = block[:4]
    dv_fator = int(block[4])
    valor_str = block[5:13]
    try:
        valor = float(valor_str) / 100.0
    except ValueError:
        valor = 0.0
    try:
        fator = int(fator_str)
    except ValueError:
        return None, valor
    if not _check_block(fator_str, dv_fator):
        return None, valor
    if fator == 0:
        return None, valor
    if fator > _MAX_FATOR:
        return None, valor
    return _FEBRABAN_EPOCH + timedelta(days=fator), valor


def parse_linha_digitavel(linha: str) -> dict:
    """Parse uma linha digitável de boleto bancário (47 dígitos).

    Levanta ValueError se a linha for inválida.
    """
    raw = _only_digits(linha)
    if len(raw) != 47:
        raise ValueError(f"Linha deve ter 47 dígitos (sem contar espaços). Recebido: {len(raw)}.")
    if raw[3] not in ("8", "9"):
        raise ValueError("Moeda inválida (esperado 8 ou 9).")
    if not _check_block(raw[:9], int(raw[9])):
        raise ValueError("DV do bloco 1 inválido.")
    if not _check_block(raw[10:20], int(raw[20])):
        raise ValueError("DV do bloco 2 inválido.")
    if not _check_block(raw[21:31], int(raw[31])):
        raise ValueError("DV do bloco 3 inválido.")
    banco = raw[:3]
    moeda = raw[3]
    agencia = raw[4:9]
    nosso_numero = raw[21:31]
    venc, valor = _parse_field5(raw[33:47])
    return {
        "banco": banco,
        "moeda": moeda,
        "valor": valor,
        "vencimento": venc,
        "agencia": agencia,
        "nosso_numero": nosso_numero,
        "raw": raw,
    }
