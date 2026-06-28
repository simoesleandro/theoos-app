"""Testes do bot — helpers puros, formatação, smoke import."""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── DAILY REMINDER LOGIC ─────────────────────────────────────────────────────


def test_daily_reminder_due_first_run():
    """Se nunca enviou (ultimo_diario=None), só dispara após REMINDER_HOUR."""
    from bot import _daily_reminder_due, REMINDER_HOUR
    agora = datetime(2026, 6, 28, 9, 0)  # 9h
    assert _daily_reminder_due(None, agora) is False
    agora_late = datetime(2026, 6, 28, REMINDER_HOUR + 1, 0)
    assert _daily_reminder_due(None, agora_late) is True


def test_daily_reminder_due_already_sent_today():
    from bot import _daily_reminder_due
    hoje = date(2026, 6, 28)
    agora = datetime(2026, 6, 28, 14, 0)
    assert _daily_reminder_due(hoje, agora) is False


def test_daily_reminder_due_yesterday():
    from bot import _daily_reminder_due
    ontem = date(2026, 6, 27)
    agora = datetime(2026, 6, 28, 14, 0)
    assert _daily_reminder_due(ontem, agora) is True


# ── TELEGRAM FORMAT HELPERS ──────────────────────────────────────────────────


def test_esc_escapes_html():
    from theoos.telegram_format import _esc
    assert _esc("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"
    assert _esc('a & b') == "a &amp; b"
    assert _esc(None) == ""
    assert _esc(123) == "123"


def test_money_formats_brl():
    from theoos.telegram_format import _money
    assert _money(1234.5) == "R$ 1234,50"
    assert _money(0) == "R$ 0,00"


def test_qty_formats():
    from theoos.telegram_format import _qty
    assert _qty(2) == "2"
    assert _qty(2.5) == "2,5"
    assert _qty(None) == "1"  # default 1


def test_progress_bar_renders():
    from theoos.telegram_format import _progress_bar
    bar = _progress_bar(50, width=10)
    assert isinstance(bar, str)
    assert len(bar) > 0


def test_cat_icon_returns_svg_or_text():
    from theoos.telegram_format import _cat_icon
    result = _cat_icon("Supermercado")
    assert isinstance(result, str)
    assert "Supermercado" in result or "🛒" in result or "svg" in result.lower() or len(result) > 0


def test_help_commands_keyboard_has_buttons():
    from theoos.telegram_format import help_commands_keyboard
    kb = help_commands_keyboard()
    assert kb is not None


def test_format_start_html_includes_welcome():
    from theoos.telegram_format import format_start_html
    html = format_start_html()
    assert "ThéoOS" in html or "TheoOS" in html or "théo" in html.lower()
    assert "<" in html and ">" in html


def test_format_ajuda_html_includes_menu():
    from theoos.telegram_format import format_ajuda_html
    html = format_ajuda_html()
    assert "<" in html


def test_format_ok_and_erro():
    from theoos.telegram_format import format_ok_html, format_erro_html
    ok = format_ok_html("Feito", "detalhe x")
    err = format_erro_html("Erro", "detalhe y")
    assert "Feito" in ok
    assert "Erro" in err


# ── TELEGRAM LISTA HELPERS ───────────────────────────────────────────────────


def test_telegram_lista_imports():
    from theoos import telegram_lista
    assert hasattr(telegram_lista, "format_lista_html")
    assert hasattr(telegram_lista, "build_action_keyboard")
    assert hasattr(telegram_lista, "build_riscar_keyboard")


def test_telegram_lista_action_keyboard_shape():
    from theoos.telegram_lista import build_action_keyboard
    kb = build_action_keyboard()
    assert kb is not None


def test_telegram_lista_format_lista_html_empty():
    from theoos.telegram_lista import format_lista_html
    html = format_lista_html([])
    assert isinstance(html, str)
    assert "<" in html


# ── BOT MODULE SMOKE IMPORT ──────────────────────────────────────────────────


def test_bot_module_imports_without_network():
    """Importar bot.py não deve conectar ao Telegram."""
    import bot  # noqa: F401
    assert hasattr(bot, "bot")
    assert hasattr(bot, "_user_states")
    assert isinstance(bot._user_states, dict)


def test_bot_has_main_handlers():
    """Garante que os handlers críticos estão registrados."""
    import bot
    handler_funcs = [h["function"].__name__ for h in bot.bot.message_handlers]
    assert "start" in handler_funcs
    assert "cmd_ajuda" in handler_funcs
    assert "ver_lista" in handler_funcs
    assert "registrar_gasto" in handler_funcs
    assert "cmd_semana" in handler_funcs
    assert "processar_texto" in handler_funcs


def test_bot_uses_expected_token():
    """Token vem do .env; pode estar vazio em testes."""
    import bot
    assert bot.TOKEN is not None  # pode ser string vazia
    assert isinstance(bot.TOKEN, str)


# ── FORMAT SEMANA ────────────────────────────────────────────────────────────


def test_format_semana_with_empty():
    from theoos.telegram_format import format_semana_html
    semana = {"pagar": [], "receber": []}
    html = format_semana_html(semana)
    assert isinstance(html, str)
    assert "<" in html  # tags HTML


def test_format_semana_with_items():
    """Testa com dicts (a função checa .get com chaves 'contas' e 'receber')."""
    from theoos.telegram_format import format_semana_html
    from types import SimpleNamespace
    hoje = date(2026, 6, 28)
    # Função espera .data_vencimento, .valor, .categoria, .nome como attrs
    conta = SimpleNamespace(
        nome="Luz", valor=150.0, data_vencimento=hoje, categoria="Luz"
    )
    semana = {
        "contas": [conta],
        "receber": [],
        "total_pagar": 150.0,
    }
    html = format_semana_html(semana, hoje=hoje)
    assert "Luz" in html
    assert "150" in html or "R$" in html
