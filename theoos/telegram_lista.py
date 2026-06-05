"""Formatação e teclado inline da lista de compras no Telegram."""
import html
import os
from collections import defaultdict
from datetime import datetime

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup


def _esc(text):
    return html.escape(str(text or ""))


def _qty_str(qty_val):
    if qty_val == int(qty_val):
        return str(int(qty_val))
    return f"{qty_val:.1f}".replace(".", ",")


def _item_line(item):
    qty = _qty_str(item.quantidade)
    marca = f" · {item.marca}" if getattr(item, "marca", None) else ""
    label = f"{item.item}{marca} — {qty} {item.unidade}"
    marcado = getattr(item, "marcado", False)
    if marcado:
        return f"  <s>☑ {_esc(label)}</s>"
    return f"  ☐ {_esc(label)}"


def calc_total_estimado(itens, item_gasto_model, db):
    """Soma preço histórico × quantidade para itens pendentes."""
    total = 0.0
    for item in itens:
        query = item_gasto_model.query.filter(
            db.or_(
                db.func.lower(item_gasto_model.nome) == db.func.lower(item.item.strip()),
                db.func.lower(item_gasto_model.nome_normalizado) == db.func.lower(item.item.strip()),
            )
        )
        if item.marca and item.marca.strip():
            query = query.filter(
                db.func.lower(item_gasto_model.marca) == db.func.lower(item.marca.strip())
            )
        ultimo = query.order_by(item_gasto_model.id.desc()).first()
        if ultimo and ultimo.valor_unitario:
            total += ultimo.valor_unitario * item.quantidade
    return total


def format_lista_html(itens, total_estimado=None):
    """Mensagem HTML para Telegram (suporta <s> riscado)."""
    if not itens:
        return "🛒 <b>ThéoOS — Lista de compras</b>\n\n✨ Lista vazia! Nada pendente."

    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    marcados = sum(1 for i in itens if getattr(i, "marcado", False))
    pendentes = len(itens) - marcados

    msg = "🛒 <b>ThéoOS — Lista de compras</b>\n"
    msg += f"📅 <i>Atualizado em {_esc(agora)}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    meta = f"📋 <b>{len(itens)}</b> itens"
    if marcados:
        meta += f" · <b>{marcados}</b> riscados · <b>{pendentes}</b> faltando"
    msg += meta + "\n\n"

    por_categoria = defaultdict(list)
    for it in itens:
        por_categoria[it.categoria or "Outros"].append(it)

    cat_icons = {
        "Supermercado": "🏪",
        "Hortifruti": "🥬",
        "Farmácia": "💊",
        "Suplemento Alimentar": "💪",
        "Outros": "📦",
    }

    for cat, items in por_categoria.items():
        icon = cat_icons.get(cat, "📦")
        msg += f"{icon} <b>{_esc(cat)}</b>\n"
        for it in items:
            msg += _item_line(it) + "\n"
        msg += "\n"

    if total_estimado and total_estimado > 0:
        msg += f"💰 <b>Total estimado:</b> R$ {_esc(f'{total_estimado:.2f}'.replace('.', ','))}\n"

    msg += "\n<i>Toque nos botões abaixo para adicionar, riscar ou sugerir melhorias.</i>"
    return msg.strip()


def web_lista_url():
    return (os.getenv("THEOOS_WEB_URL") or "http://localhost:5000").rstrip("/") + "/lista"


def telegram_url_ok(url):
    """Telegram rejeita localhost em botões URL — só http(s) com host acessível."""
    if not url:
        return False
    lower = url.lower()
    if "localhost" in lower or "127.0.0.1" in lower:
        return False
    return lower.startswith("http://") or lower.startswith("https://")


def build_action_keyboard():
    """Teclado principal: adicionar, atualizar, app, melhoria, riscar."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ Adicionar item", callback_data="lista_add"),
        InlineKeyboardButton("🔄 Atualizar", callback_data="lista_refresh"),
    )
    app_url = web_lista_url()
    if telegram_url_ok(app_url):
        markup.add(
            InlineKeyboardButton("🌐 Abrir no app", url=app_url),
            InlineKeyboardButton("💡 Sugerir melhoria", callback_data="lista_melhoria"),
        )
    else:
        markup.add(
            InlineKeyboardButton("🌐 Link do app", callback_data="lista_open"),
            InlineKeyboardButton("💡 Sugerir melhoria", callback_data="lista_melhoria"),
        )
    markup.add(InlineKeyboardButton("✅ Riscar / desmarcar", callback_data="lista_riscar_menu"))
    return markup


def build_riscar_keyboard(itens):
    """Um botão por item pendente — alterna riscado."""
    markup = InlineKeyboardMarkup(row_width=1)
    for it in itens:
        marcado = getattr(it, "marcado", False)
        prefix = "☑" if marcado else "☐"
        nome = (it.item or "")[:40]
        markup.add(
            InlineKeyboardButton(
                f"{prefix} {nome}",
                callback_data=f"lista_toggle:{it.id}",
            )
        )
    markup.add(InlineKeyboardButton("« Voltar à lista", callback_data="lista_refresh"))
    return markup


def send_lista_message(bot, chat_id, itens, total_estimado=None):
    """Envia (ou reenvia) a lista formatada com teclado inline."""
    text = format_lista_html(itens, total_estimado=total_estimado)
    if len(text) > 4000:
        text = text[:3900] + "\n\n<i>(lista truncada)</i>"
    return bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=build_action_keyboard(),
        disable_web_page_preview=True,
    )
