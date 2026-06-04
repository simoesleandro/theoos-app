"""Conciliação simples via CSV de extrato."""
import csv
import io
from datetime import datetime


def parse_bank_csv(file_bytes, encoding="utf-8"):
    """Retorna lista de {data, descricao, valor} (débitos negativos normalizados positivos)."""
    text = file_bytes.decode(encoding, errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []

    header = [c.lower().strip() for c in rows[0]]
    start = 1 if any(k in "".join(header) for k in ("data", "valor", "desc")) else 0

    out = []
    for row in rows[start:]:
        if len(row) < 2:
            continue
        try:
            if len(row) >= 3:
                data_str, desc, val_str = row[0], row[1], row[-1]
            else:
                data_str, val_str = row[0], row[1]
                desc = "Lançamento CSV"
            val_str = val_str.replace("R$", "").replace(".", "").replace(",", ".").strip()
            valor = abs(float(val_str))
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    dt = datetime.strptime(data_str.strip()[:10], fmt).date()
                    break
                except ValueError:
                    dt = None
            if dt is None:
                continue
            out.append({"data": dt, "descricao": desc.strip()[:120], "valor": valor})
        except (ValueError, IndexError):
            continue
    return out


def match_against_financas(lancamentos, Financas, tolerance=0.02):
    """Marca lançamentos já existentes em Financas (valor + data próxima)."""
    existentes = Financas.query.filter_by(tipo="debito").all()
    resultado = []
    for lan in lancamentos:
        matched = False
        for fin in existentes:
            if fin.data and abs(fin.valor - lan["valor"]) <= tolerance:
                if fin.data.date() == lan["data"]:
                    matched = True
                    break
        resultado.append({**lan, "conciliado": matched, "novo": not matched})
    return resultado
