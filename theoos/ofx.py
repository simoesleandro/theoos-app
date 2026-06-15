"""Gerador de OFX (Open Financial Exchange) 1.x (SGML flavor).

OFX é o formato padrão para importar transações em apps de banco/finanças.
Esta implementação cobre o subset mínimo necessário (Bank Statement):
- BANKACCTFROM / BANKACCTTO
- STMTTRN (transação) com TRNTYPE, DTPOSTED, TRNAMT, FITID, NAME, MEMO
- Saldo de fechamento (BALAMT)

Suporta OFX 1.x (SGML) — apps modernos (GnuCash, Moneydance, OFX clients)
aceitam ambos SGML e XML, mas SGML é mais permissivo (sem fechamento de
tags obrigatório).
"""
from __future__ import annotations

from datetime import datetime
from io import StringIO

OFX_HEADER = (
    "OFXHEADER:100\n"
    "DATA:OFXSGML\n"
    "VERSION:102\n"
    "SECURITY:NONE\n"
    "ENCODING:UTF-8\n"
    "CHARSET:CSUNICODE\n"
    "COMPRESSION:NONE\n"
    "OLDFILEUID:NONE\n"
    "NEWFILEUID:NONE\n"
    "\n"
)


def _format_date(dt: datetime) -> str:
    """OFX 1.x: YYYYMMDDHHMMSS[.XXX][TZ] (TZ opcional)."""
    return dt.strftime("%Y%m%d%H%M%S")


def _format_amount(value: float) -> str:
    """OFX usa ponto decimal e sem separador de milhar. Negativos com sinal."""
    if value < 0:
        return f"-{abs(value):.2f}"
    return f"{value:.2f}"


def _build_stmtr(
    transactions: list[dict],
    account_id: str = "THOOS-001",
    bank_id: str = "0000",
    ledger_balance: float = 0.0,
) -> str:
    """Monta o STMTRS (statement) OFX."""
    buf = StringIO()
    buf.write("<STMTRS>\n")
    buf.write("<CURDEF>BRL</CURDEF>\n")
    buf.write("<BANKACCTFROM>\n")
    buf.write("<BANKID>{}</BANKID>\n".format(bank_id))
    buf.write("<ACCTID>{}</ACCTID>\n".format(account_id))
    buf.write("<ACCTTYPE>CHECKING</ACCTTYPE>\n")
    buf.write("</BANKACCTFROM>\n")
    buf.write("<BANKTRANLIST>\n")
    if transactions:
        first = min(t["data"] for t in transactions)
        last = max(t["data"] for t in transactions)
        buf.write("<DTSTART>{}</DTSTART>\n".format(_format_date(first)))
        buf.write("<DTEND>{}</DTEND>\n".format(_format_date(last)))
    for t in transactions:
        buf.write("<STMTTRN>\n")
        buf.write("<TRNTYPE>{}</TRNTYPE>\n".format(t.get("trntype", "DEBIT" if t["valor"] < 0 else "CREDIT")))
        buf.write("<DTPOSTED>{}</DTPOSTED>\n".format(_format_date(t["data"])))
        buf.write("<TRNAMT>{}</TRNAMT>\n".format(_format_amount(t["valor"])))
        buf.write("<FITID>{}</FITID>\n".format(t.get("fitid", f"T{t['data'].strftime('%Y%m%d%H%M%S')}")))
        buf.write("<NAME>{}</NAME>\n".format(_xml_escape(t.get("name", ""))[:32]))
        memo = t.get("memo")
        if memo:
            buf.write("<MEMO>{}</MEMO>\n".format(_xml_escape(memo)[:90]))
        buf.write("</STMTTRN>\n")
    buf.write("</BANKTRANLIST>\n")
    buf.write("<LEDGERBAL>\n")
    bal_dt = max((t["data"] for t in transactions), default=datetime.now())
    buf.write("<DTASOF>{}</DTASOF>\n".format(_format_date(bal_dt)))
    buf.write("<BALAMT>{}</BALAMT>\n".format(_format_amount(ledger_balance)))
    buf.write("</LEDGERBAL>\n")
    buf.write("</STMTRS>\n")
    return buf.getvalue()


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_ofx(
    transactions: list[dict],
    *,
    org: str = "ThéoOS",
    fid: str = "0000",
    account_id: str = "THOOS-001",
    ledger_balance: float = 0.0,
) -> str:
    """Gera um OFX 1.x completo (com header SGML).

    Cada transação é um dict com chaves:
        data: datetime
        valor: float (negativo = débito)
        name: str (descrição curta)
        memo: str (opcional)
        fitid: str (opcional, ID único)
        trntype: str (opcional, default CREDIT/DEBIT pelo sinal)
    """
    parts = [OFX_HEADER]
    parts.append("<OFX>\n")
    parts.append("<SIGNONMSGSRSV1>\n")
    parts.append("<SONRS>\n")
    parts.append("<STATUS>\n<CODE>0</CODE>\n<SEVERITY>INFO</SEVERITY>\n</STATUS>\n")
    parts.append("<DTSERVER>{}</DTSERVER>\n".format(_format_date(datetime.now())))
    parts.append("<LANGUAGE>POR</LANGUAGE>\n")
    parts.append("</SONRS>\n")
    parts.append("</SIGNONMSGSRSV1>\n")
    parts.append("<BANKMSGSRSV1>\n")
    parts.append("<STMTMSGSRSV1>\n")
    parts.append(_build_stmtr(transactions, account_id=account_id, bank_id=fid, ledger_balance=ledger_balance))
    parts.append("</STMTMSGSRSV1>\n")
    parts.append("</BANKMSGSRSV1>\n")
    parts.append("</OFX>\n")
    return "".join(parts)
