"""Relatório mensal em PDF (fpdf2)."""
from calendar import monthrange
from datetime import date, datetime

from fpdf import FPDF


def _safe(text):
    if text is None:
        return ""
    s = str(text)
    return s.encode("latin-1", "replace").decode("latin-1")


class TheoPDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, _safe(f"ThéoOS — pagina {self.page_no()}"), align="C")


def build_monthly_pdf(
    year: int,
    month: int,
    debitos: float,
    creditos: float,
    transacoes: list,
    gastos_cat: list,
    contas_pendentes: list,
):
    """Gera bytes do PDF do mês."""
    pdf = TheoPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 30, 30)
    titulo = f"Relatorio Financeiro — {month:02d}/{year}"
    pdf.cell(0, 10, _safe(titulo), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}"), ln=True)
    pdf.ln(4)

    saldo = creditos - debitos
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Resumo do mes", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for label, val, color in (
        ("Receitas", creditos, (40, 160, 100)),
        ("Despesas", debitos, (200, 80, 80)),
        ("Saldo liquido", saldo, (40, 160, 100) if saldo >= 0 else (200, 80, 80)),
    ):
        pdf.set_text_color(*color)
        pdf.cell(95, 7, _safe(label))
        pdf.cell(0, 7, _safe(f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")), ln=True)
    pdf.set_text_color(30, 30, 30)
    pdf.ln(3)

    if gastos_cat:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Gastos por categoria", ln=True)
        pdf.set_font("Helvetica", "", 9)
        for cat, val in gastos_cat[:12]:
            pdf.cell(100, 6, _safe(cat))
            pdf.cell(0, 6, _safe(f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")), ln=True)
        pdf.ln(3)

    if contas_pendentes:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Contas pendentes (vencimento no mes ou atrasadas)", ln=True)
        pdf.set_font("Helvetica", "", 9)
        for c in contas_pendentes[:20]:
            linha = f"{c['nome']} — vence {c['vencimento']} — R$ {c['valor']:.2f}"
            pdf.cell(0, 6, _safe(linha), ln=True)
        pdf.ln(3)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, f"Transacoes ({len(transacoes)})", ln=True)
    pdf.set_font("Helvetica", "", 8)
    for t in transacoes[:40]:
        sinal = "+" if t["tipo"] == "credito" else "-"
        linha = f"{t['data']}  {sinal} R$ {t['valor']:.2f}  {t['descricao'][:60]}"
        pdf.cell(0, 5, _safe(linha), ln=True)
    if len(transacoes) > 40:
        pdf.cell(0, 5, _safe(f"... e mais {len(transacoes) - 40} lancamentos"), ln=True)

    raw = pdf.output()
    return raw if isinstance(raw, (bytes, bytearray)) else raw.encode("latin-1")


def month_bounds(year: int, month: int):
    primeiro = datetime(year, month, 1)
    ultimo_dia = monthrange(year, month)[1]
    ultimo = datetime(year, month, ultimo_dia, 23, 59, 59)
    return primeiro, ultimo
