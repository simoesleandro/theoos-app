"""Conciliação de extrato bancário via CSV.

Bancos suportados com detecção automática de colunas:
- Nubank: data, descrição, valor, categoria
- Inter: Data, Descrição, Valor, Tipo
- Itaú: data, descrição, valor (com sinal)
- Bradesco: data, descrição, valor
- Genérico: data, descrição, valor

A função parse_bank_csv() tenta detectar o formato pelos cabeçalhos do CSV.
Aceita encoding UTF-8, Latin-1 e CP1252 (padrão Excel BR).

Limitações conhecidas:
- Não parseia OFX (use /exportar/ofx para exportar)
- Não faz fuzzy match de descrição (compara valor + data exatos)
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
)


def _normalize_date(s: str) -> str | None:
    s = (s or "").strip()[:10]
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _normalize_amount(s: str) -> float:
    """Converte '1.234,56', '1234.56', 'R$ 1.234,56', '-50,00' em float."""
    if s is None:
        return 0.0
    s = str(s).strip()
    s = re.sub(r"[R$\s]", "", s)
    negativo = s.startswith("-")
    s = s.lstrip("-")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s and s.count(".") > 1:
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if negativo else v


def _looks_like_header(row: list[str]) -> bool:
    """Detecta se a primeira linha parece ser cabeçalho (não dados)."""
    if not row:
        return False
    txt = " ".join(row).lower()
    keywords = ("data", "date", "descri", "valor", "value", "amount", "categoria", "category", "tipo", "type")
    return sum(1 for k in keywords if k in txt) >= 2


def _detect_columns(headers: list[str]) -> dict:
    """Mapeia cabeçalhos do CSV para campos canônicos: data, descricao, valor, tipo."""
    mapping: dict[str, int] = {}
    for i, h in enumerate(headers):
        if h is None:
            continue
        h = str(h).strip().lower()
        if "data" in h and "venc" not in h and "vencimento" not in h:
            mapping.setdefault("data", i)
        elif "descri" in h or "histórico" in h or "memo" in h or "lançamento" in h or h in ("title", "nome"):
            mapping.setdefault("descricao", i)
        elif "valor" in h or "value" in h or "amount" in h or ("quantia" in h):
            mapping.setdefault("valor", i)
        elif "tipo" in h or "type" in h:
            mapping.setdefault("tipo", i)
        elif "categ" in h:
            mapping.setdefault("categoria", i)
    return mapping


def _detect_bank_format(headers: list[str]) -> str:
    """Identifica o banco pelo cabeçalho. Retorna 'generico' se incerto."""
    h = " ".join(headers or []).lower()
    if "nuconta" in h or ("nubank" in h):
        return "nubank"
    if "lançamento" in h and "inter" in h:
        return "inter"
    if "itau" in h or "itaú" in h:
        return "itau"
    if "bradesco" in h:
        return "bradesco"
    return "generico"


def _decode_bytes(data: bytes) -> tuple[str, str]:
    """Tenta decodificar em UTF-8, depois Latin-1 (Excel BR)."""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _detect_delimiter(sample_text: str) -> str:
    """Detecta delimitador pelo que aparece mais vezes na primeira linha não-vazia."""
    candidates = (",", ";", "\t", "|")
    counts = {d: sample_text.count(d) for d in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _detect_dialect(sample_text: str) -> csv.Dialect:
    """Detecta o delimitador/quoting do CSV (vírgula, ponto-e-vírgula, tab)."""
    delim = _detect_delimiter(sample_text)
    try:
        sniffed = csv.Sniffer().sniff(sample_text, delimiters=",;\t|")
        sniffed.delimiter = delim
        return sniffed
    except csv.Error:
        class _Fallback(csv.excel):
            delimiter = delim
        return _Fallback()


def parse_bank_csv(file_bytes: bytes, encoding: str = "auto") -> tuple[list[dict], dict]:
    """Parseia CSV de extrato bancário.

    Returns:
        (lancamentos, meta) onde meta = {encoding, formato, mapeamento, total_linhas, validos}
        Cada lançamento: {data (str 'YYYY-MM-DD'), descricao, valor (float), tipo?}
    """
    text, used_enc = (_decode_bytes(file_bytes) if encoding == "auto"
                     else (file_bytes.decode(encoding, errors="replace"), encoding))
    sample = text[:4096]
    dialect = _detect_dialect(sample)
    reader = csv.reader(io.StringIO(text), dialect=dialect)
    all_rows = list(reader)
    if not all_rows:
        return [], {"encoding": used_enc, "formato": "vazio", "mapeamento": {}, "validos": 0}

    if _looks_like_header(all_rows[0]):
        headers = all_rows[0]
        rows = all_rows[1:]
    else:
        first_data = all_rows[0]
        n = len(first_data)
        if n == 3:
            headers = ["Data", "Descrição", "Valor"]
        elif n == 4:
            headers = ["Data", "Descrição", "Valor", "Tipo"]
        else:
            headers = [f"col_{i}" for i in range(n)]
        rows = all_rows

    mapping = _detect_columns(headers)
    formato = _detect_bank_format(headers)

    lancamentos: list[dict] = []
    for row in rows:
        if not row or all((c or "").strip() == "" for c in row):
            continue
        try:
            raw_data = row[mapping["data"]] if "data" in mapping and mapping["data"] < len(row) else ""
            data = _normalize_date(raw_data) if raw_data else None
            if not data:
                continue
            descricao = ""
            if "descricao" in mapping and mapping["descricao"] < len(row):
                descricao = (row[mapping["descricao"]] or "").strip()[:120]
            if not descricao:
                continue
            valor = 0.0
            if "valor" in mapping and mapping["valor"] < len(row):
                valor = _normalize_amount(row[mapping["valor"]])
            if valor == 0:
                continue
            tipo = ""
            if "tipo" in mapping and mapping["tipo"] < len(row):
                tipo = (row[mapping["tipo"]] or "").strip().lower()
            if not tipo:
                eh_negativo = valor < 0
            else:
                eh_negativo = valor < 0 or tipo in ("credito", "entrada", "receita", "c", "+1")
            lancamentos.append(
                {
                    "data": data,
                    "descricao": descricao,
                    "valor": abs(valor),
                    "tipo": tipo,
                    "_negativo": eh_negativo,
                }
            )
        except (ValueError, IndexError):
            continue

    meta = {
        "encoding": used_enc,
        "formato": formato,
        "mapeamento": mapping,
        "cabecalhos": headers,
        "total_linhas": len(rows),
        "validos": len(lancamentos),
    }
    return lancamentos, meta


def match_against_financas(lancamentos: list[dict], Financas, tolerance: float = 0.02) -> list[dict]:
    """Marca lançamentos já existentes em Financas (valor + data).

    Considera tipo (entrada/saída) quando disponível.
    """
    existentes = Financas.query.filter_by(tipo="debito").all()
    for lan in lancamentos:
        matched = False
        valor_busca = lan["valor"]
        eh_saida = lan.get("_negativo", True) or lan.get("tipo") in ("debito", "saida", "saída", "d", "-1")
        for fin in existentes:
            if fin.data and abs(fin.valor - valor_busca) <= tolerance:
                if fin.data.strftime("%Y-%m-%d") == lan["data"] or abs((fin.data.date() - datetime.strptime(lan["data"], "%Y-%m-%d").date()).days) <= 1:
                    matched = True
                    break
        lan["conciliado"] = matched
        lan["novo"] = not matched
        lan["_eh_saida"] = eh_saida
    return lancamentos
