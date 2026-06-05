"""Relatorio mensal em PDF (fpdf2) — layout alinhado ao design ThéoOS."""
from calendar import monthrange
from datetime import datetime

from fpdf import FPDF

# Paleta ThéoOS (RGB)
BRAND = (45, 212, 191)
SLATE_MID = (30, 36, 48)
CARD_BG = (245, 247, 250)
BORDER = (220, 226, 235)
TEXT = (24, 28, 36)
MUTED = (110, 118, 132)
SUCCESS = (52, 211, 153)
DANGER = (248, 113, 113)
WHITE = (255, 255, 255)

MARGIN = 14
PAGE_W = 210
TABLE_W = PAGE_W - MARGIN * 2  # 182mm — largura fixa para todas as tabelas
ROW_H = 6
HEADER_H = 7
PAGE_BOTTOM = 275

MESES = (
    "", "Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)


def _safe(text):
    if text is None:
        return ""
    s = str(text)
    for ch in ("—", "–", "−", "•"):
        s = s.replace(ch, "-")
    return s.encode("latin-1", "replace").decode("latin-1")


def _money(val):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "R$ 0,00"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class TheoPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(auto=True, margin=20)

    def add_page(self, *args, **kwargs):
        super().add_page(*args, **kwargs)
        self.set_x(MARGIN)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*BORDER)
        self.line(MARGIN, self.get_y(), PAGE_W - MARGIN, self.get_y())
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 8, _safe(f"TheoOS  |  Pagina {self.page_no()}"), align="C")


def _draw_header(pdf, year, month):
    pdf.set_fill_color(*BRAND)
    pdf.rect(0, 0, PAGE_W, 26, style="F")
    pdf.set_xy(MARGIN, 7)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 7, _safe("TheoOS"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(MARGIN)
    pdf.set_font("Helvetica", "", 10)
    nome_mes = MESES[month] if 1 <= month <= 12 else f"{month:02d}"
    pdf.cell(0, 5, _safe(f"Relatorio Financeiro - {nome_mes}/{year}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(MARGIN, 30)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(
        0, 5,
        _safe(f"Gerado em {datetime.now().strftime('%d/%m/%Y as %H:%M')}"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(4)


def _draw_kpi_row(pdf, creditos, debitos, saldo, n_trans):
    """4 cards na mesma largura da pagina (sem cortar)."""
    y0 = pdf.get_y()
    gap = 3
    card_w = (TABLE_W - gap * 3) / 4
    card_h = 24
    items = (
        ("RECEITAS", _money(creditos), SUCCESS),
        ("DESPESAS", _money(debitos), DANGER),
        ("SALDO", _money(saldo), SUCCESS if saldo >= 0 else DANGER),
        ("LANCAM.", str(n_trans), BRAND),
    )
    x = MARGIN
    for label, valor, color in items:
        pdf.set_fill_color(*CARD_BG)
        pdf.set_draw_color(*BORDER)
        pdf.rect(x, y0, card_w, card_h, style="FD")
        pdf.set_fill_color(*color)
        pdf.rect(x, y0, card_w, 2, style="F")
        pdf.set_xy(x + 3, y0 + 4)
        pdf.set_font("Helvetica", "", 6)
        pdf.set_text_color(*MUTED)
        pdf.cell(card_w - 6, 3, _safe(label))
        pdf.set_xy(x + 3, y0 + 9)
        fs = 12 if label == "LANCAM." else 8
        pdf.set_font("Helvetica", "B", fs)
        pdf.set_text_color(*color if label != "LANCAM." else TEXT)
        pdf.cell(card_w - 6, 7, _safe(valor), align="R")
        x += card_w + gap

    pdf.set_y(y0 + card_h + 6)


def _section_title(pdf, title):
    if pdf.get_y() > PAGE_BOTTOM - 20:
        pdf.add_page()
    pdf.ln(2)
    y = pdf.get_y()
    pdf.set_fill_color(*BRAND)
    pdf.rect(MARGIN, y, 3, 7, style="F")
    pdf.set_xy(MARGIN + 5, y)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*TEXT)
    pdf.cell(0, 7, _safe(title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _table_header(pdf, cols, widths, align=None):
    align = align or ["L"] * len(cols)
    pdf.set_x(MARGIN)
    pdf.set_fill_color(*SLATE_MID)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_draw_color(*SLATE_MID)
    for col, w, al in zip(cols, widths, align):
        pdf.cell(w, HEADER_H, _safe(col), border=1, align=al, fill=True)
    pdf.ln()


def _ensure_table_space(pdf, cols, widths, align, rows_needed=1):
    """Nova pagina + repetir cabecalho se faltar espaco."""
    needed = ROW_H * rows_needed + HEADER_H
    if pdf.get_y() + needed > PAGE_BOTTOM:
        pdf.add_page()
        _table_header(pdf, cols, widths, align)


def _table_row(pdf, cells, widths, align=None, fill=False, colors=None):
    align = align or ["L"] * len(cells)
    colors = colors or [TEXT] * len(cells)
    pdf.set_x(MARGIN)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_draw_color(*BORDER)
    if fill:
        pdf.set_fill_color(*CARD_BG)
    for cell, w, al, col in zip(cells, widths, align, colors):
        pdf.set_text_color(*col)
        pdf.cell(w, ROW_H, _safe(str(cell)[:90]), border=1, align=al, fill=fill)
    pdf.ln()


# Larguras fixas (somam TABLE_W = 182)
W_CAT = [108, 37, 37]
W_CONTAS = [108, 37, 37]
W_TX = [24, 18, 34, 106]


def _section_categorias(pdf, gastos_cat, total_debitos):
    if not gastos_cat:
        return
    _section_title(pdf, "Gastos por categoria")
    cols = ["Categoria", "Valor", "% do mes"]
    align = ["L", "R", "R"]
    _table_header(pdf, cols, W_CAT, align)
    for i, (cat, val) in enumerate(gastos_cat[:12]):
        _ensure_table_space(pdf, cols, W_CAT, align)
        pct = (val / total_debitos * 100) if total_debitos > 0 else 0
        _table_row(pdf, [cat, _money(val), f"{pct:.1f}%"], W_CAT, align, fill=i % 2 == 0)
    pdf.ln(4)


def _section_contas(pdf, contas_pendentes):
    if not contas_pendentes:
        return
    _section_title(pdf, f"Contas pendentes ({len(contas_pendentes)})")
    cols = ["Conta", "Vencimento", "Valor"]
    align = ["L", "C", "R"]
    _table_header(pdf, cols, W_CONTAS, align)
    total = 0.0
    for i, c in enumerate(contas_pendentes[:25]):
        _ensure_table_space(pdf, cols, W_CONTAS, align)
        total += c["valor"]
        _table_row(
            pdf,
            [c["nome"], c["vencimento"], _money(c["valor"])],
            W_CONTAS,
            align,
            fill=i % 2 == 0,
        )
    _ensure_table_space(pdf, cols, W_CONTAS, align)
    pdf.set_x(MARGIN)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*TEXT)
    pdf.set_draw_color(*BORDER)
    pdf.cell(W_CONTAS[0], ROW_H, _safe("Total pendente"), border=1)
    pdf.cell(W_CONTAS[1], ROW_H, "", border=1)
    pdf.cell(W_CONTAS[2], ROW_H, _safe(_money(total)), border=1, align="R")
    pdf.ln(8)


def _section_transacoes(pdf, transacoes):
    _section_title(pdf, f"Transacoes do mes ({len(transacoes)})")
    if not transacoes:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 6, _safe("Nenhuma transacao neste periodo."), new_x="LMARGIN", new_y="NEXT")
        return

    cols = ["Data", "Tipo", "Valor", "Descricao"]
    align = ["C", "C", "R", "L"]
    _table_header(pdf, cols, W_TX, align)
    shown = transacoes[:40]
    for i, t in enumerate(shown):
        _ensure_table_space(pdf, cols, W_TX, align)
        is_cred = t.get("tipo") == "credito"
        tipo = "Entrada" if is_cred else "Saida"
        val_color = SUCCESS if is_cred else DANGER
        desc = (t.get("descricao") or "")[:85]
        _table_row(
            pdf,
            [t["data"], tipo, _money(t["valor"]), desc],
            W_TX,
            align,
            fill=i % 2 == 0,
            colors=[TEXT, val_color, val_color, TEXT],
        )
    if len(transacoes) > 40:
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, _safe(f"... e mais {len(transacoes) - 40} lancamentos"), new_x="LMARGIN", new_y="NEXT")


def build_monthly_pdf(
    year: int,
    month: int,
    debitos: float,
    creditos: float,
    transacoes: list,
    gastos_cat: list,
    contas_pendentes: list,
):
    """Gera bytes do PDF do mes."""
    pdf = TheoPDF()
    pdf.add_page()

    _draw_header(pdf, year, month)
    saldo = creditos - debitos
    _draw_kpi_row(pdf, creditos, debitos, saldo, len(transacoes))

    _section_categorias(pdf, gastos_cat, debitos)
    _section_contas(pdf, contas_pendentes)
    _section_transacoes(pdf, transacoes)

    raw = pdf.output()
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    return str(raw).encode("latin-1")


def month_bounds(year: int, month: int):
    primeiro = datetime(year, month, 1)
    ultimo_dia = monthrange(year, month)[1]
    ultimo = datetime(year, month, ultimo_dia, 23, 59, 59)
    return primeiro, ultimo
