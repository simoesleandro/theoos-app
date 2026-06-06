"""Formatação HTML das mensagens automáticas do Telegram."""
import html
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

SEP = "━━━━━━━━━━━━━━━━━━━━"
_WEEKDAY = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")

CAT_ICONS = {
    "Supermercado": "🏪",
    "Hortifruti": "🥬",
    "Farmácia": "💊",
    "Suplemento Alimentar": "💪",
    "Atividades Théo": "🧒",
    "Saúde": "💊",
    "Financiamento": "🏠",
    "Luz": "💡",
    "Internet": "📡",
    "Condomínio": "🏢",
    "Cartão de Crédito": "💳",
    "Contas Fixas": "📋",
    "Outros": "📦",
}


def _esc(text):
    return html.escape(str(text or ""))


def _money(val):
    return f"R$ {float(val):.2f}".replace(".", ",")


def _qty(val):
    q = float(val or 1)
    if q == int(q):
        return str(int(q))
    return f"{q:.1f}".replace(".", ",")


def _cat_icon(categoria):
    return CAT_ICONS.get(categoria or "Outros", "📦")


def _dia_label(dt, hoje):
    delta = (dt - hoje).days
    if delta == 0:
        return "Hoje"
    if delta == 1:
        return "Amanhã"
    return f"{_WEEKDAY[dt.weekday()]} · em {delta}d"


def _conta_card_line(conta):
    return (
        f"{_cat_icon(conta.categoria)} <b>{_esc(conta.nome)}</b>\n"
        f"   {_money(conta.valor)} · <i>{_esc(conta.categoria or 'Outros')}</i>\n"
    )


def _receber_card_line(item):
    return (
        f"💰 <b>{_esc(item.nome)}</b>\n"
        f"   {_money(item.valor)} · <i>{_esc(item.categoria or 'Outros')}</i>\n"
    )


def _blockquote(title, body):
    """Card colapsável (blockquote expandível do Telegram)."""
    return f"<blockquote expandable>{title}\n\n{body.rstrip()}</blockquote>"


def _web_url(path):
    base = (os.getenv("THEOOS_WEB_URL") or "http://localhost:5000").rstrip("/")
    return f"{base}{path}"


def semana_keyboard():
    """Botões para abrir o painel web."""
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    from theoos.telegram_lista import telegram_url_ok

    markup = InlineKeyboardMarkup(row_width=2)
    contas_url = _web_url("/contas")
    receber_url = _web_url("/receber")
    if telegram_url_ok(contas_url):
        markup.add(
            InlineKeyboardButton("💸 Contas a pagar", url=contas_url),
            InlineKeyboardButton("💰 A receber", url=receber_url),
        )
    else:
        markup.add(InlineKeyboardButton("🌐 Abrir ThéoOS", callback_data="lista_open"))
    markup.add(InlineKeyboardButton("🔄 Atualizar", callback_data="semana_refresh"))
    return markup


def format_semana_html(semana, hoje=None, days=7, max_por_card=6):
    """
    Agenda semanal estilo app — cards por status/data + resumo no topo.
    Telegram não tem cards nativos; usamos blockquote expandível.
    """
    hoje = hoje or date.today()
    limite = hoje + timedelta(days=days)
    contas = semana.get("contas") or []
    receber = semana.get("receber") or []

    msg = "📅 <b>ThéoOS</b> · Agenda financeira\n"
    msg += f"<i>{hoje.strftime('%d/%m/%Y')} → {limite.strftime('%d/%m/%Y')}</i>\n"
    msg += f"{SEP}\n\n"

    msg += "📊 <b>Resumo da semana</b>\n"
    msg += f"💸 A pagar · <b>{_money(semana.get('total_pagar', 0))}</b>"
    msg += f" · {len(contas)} conta(s)\n"
    if receber:
        msg += f"💰 A receber · <b>{_money(semana.get('total_receber', 0))}</b>"
        msg += f" · {len(receber)} item(ns)\n"
    msg += "\n"

    vencidas = [c for c in contas if c.data_vencimento < hoje]
    proximas = [c for c in contas if c.data_vencimento >= hoje]

    if vencidas:
        total_v = sum(c.valor for c in vencidas)
        body = ""
        for c in vencidas[:max_por_card]:
            dias = (hoje - c.data_vencimento).days
            body += _conta_card_line(c)
            body += f"   ⏰ venceu <b>{c.data_vencimento.strftime('%d/%m')}</b> · {dias}d atrás\n"
        if len(vencidas) > max_por_card:
            body += f"\n<i>+{len(vencidas) - max_por_card} conta(s)…</i>\n"
        title = f"🔴 <b>Vencidas</b> · {_money(total_v)} · {len(vencidas)} conta(s)"
        msg += _blockquote(title, body) + "\n\n"

    by_date = defaultdict(list)
    for c in proximas:
        by_date[c.data_vencimento].append(c)

    for dt in sorted(by_date.keys()):
        items = by_date[dt]
        sub = sum(c.valor for c in items)
        label = _dia_label(dt, hoje)
        body = ""
        for c in items[:max_por_card]:
            body += _conta_card_line(c)
        if len(items) > max_por_card:
            body += f"\n<i>+{len(items) - max_por_card} conta(s) neste dia…</i>\n"
        title = f"📌 <b>{dt.strftime('%d/%m')}</b> · {label} · {_money(sub)}"
        msg += _blockquote(title, body) + "\n\n"

    if receber:
        by_rec = defaultdict(list)
        for r in receber:
            by_rec[r.data_esperada].append(r)
        for dt in sorted(by_rec.keys()):
            items = by_rec[dt]
            sub = sum(r.valor for r in items)
            label = _dia_label(dt, hoje)
            body = ""
            for r in items[:max_por_card]:
                body += _receber_card_line(r)
            if len(items) > max_por_card:
                body += f"\n<i>+{len(items) - max_por_card} item(ns)…</i>\n"
            title = f"💵 <b>Receber {dt.strftime('%d/%m')}</b> · {label} · {_money(sub)}"
            msg += _blockquote(title, body) + "\n\n"

    msg += "<i>Toque ▶ em cada card para expandir · use os botões abaixo para detalhes no app</i>"
    return msg.strip()


def _shell(title, subtitle=None):
    msg = f"{title}\n"
    if subtitle:
        msg += f"<i>{subtitle}</i>\n"
    msg += f"{SEP}\n\n"
    return msg


def _progress_bar(pct, width=10):
    pct = max(0, min(100, float(pct)))
    filled = round(width * pct / 100)
    return "▓" * filled + "░" * (width - filled)


COMMAND_HELP = {
    "comprar": {
        "icon": "🛒",
        "button": "/comprar",
        "title": "Adicionar à lista",
        "body": (
            "Adiciona um item à lista de compras.\n\n"
            "Digite o comando seguido do produto:\n"
            "<code>/comprar Frango 2kg</code>\n"
            "<code>/comprar Leite 2 un</code>"
        ),
    },
    "lista": {
        "icon": "📋",
        "button": "/lista",
        "title": "Lista de compras",
        "body": (
            "Mostra todos os itens pendentes, agrupados por categoria.\n\n"
            "Inclui botões para adicionar, riscar itens, atualizar e abrir o painel web."
        ),
    },
    "gasto": {
        "icon": "💸",
        "button": "/gasto",
        "title": "Gasto manual",
        "body": (
            "Registra um gasto avulso sem cupom fiscal.\n\n"
            "Formato: valor + descrição\n"
            "<code>/gasto 10.50 Chocolate</code>\n"
            "<code>/gasto 45.00 Uber</code>"
        ),
    },
    "relatorio": {
        "icon": "📊",
        "button": "/relatorio",
        "title": "Relatório financeiro",
        "body": (
            "Resumo do mês: totais por categoria, saldo e últimos lançamentos.\n\n"
            "Ideal para uma visão rápida das finanças da família."
        ),
    },
    "semana": {
        "icon": "📅",
        "button": "/semana",
        "title": "Agenda da semana",
        "body": (
            "Contas a pagar, vencidas e receitas nos próximos 7 dias.\n\n"
            "Cards por data com totais e botões para abrir Contas / Receber no app."
        ),
    },
    "orcamento": {
        "icon": "📈",
        "button": "/orcamento",
        "title": "Orçamento do mês",
        "body": (
            "Status dos limites por categoria: quanto já gastou e quanto falta.\n\n"
            "Alertas quando uma categoria passa de 80% do limite."
        ),
    },
    "lembretes": {
        "icon": "⏰",
        "button": "/lembretes",
        "title": "Lembretes de vencimento",
        "body": (
            "Dispara agora os alertas de contas vencidas e vencimentos próximos.\n\n"
            "<i>Automático:</i> todo dia às 10h o bot envia os avisos sozinho."
        ),
    },
    "ajuda": {
        "icon": "📖",
        "button": "/ajuda",
        "title": "Guia completo",
        "body": (
            "Mostra este menu com botões e explicação de cada função.\n\n"
            "Use sempre que tiver dúvida de como falar com o bot."
        ),
    },
    "cupom": {
        "icon": "📸",
        "button": "Cupom",
        "title": "Foto de cupom fiscal",
        "body": (
            "Envie a foto do cupom — a IA lê os itens, registra os gastos "
            "e dá baixa na lista quando reconhece produtos.\n\n"
            "<i>Cupons duplicados são ignorados automaticamente.</i>"
        ),
    },
    "texto": {
        "icon": "💬",
        "button": "Texto/áudio",
        "title": "Texto ou áudio livre",
        "body": (
            "Escreva o item direto no chat (ex: <i>Leite 2 un</i>) ou grave um áudio "
            "listando produtos — a IA interpreta e adiciona à lista.\n\n"
            "Não precisa usar comando nesses casos."
        ),
    },
}

HELP_COMMANDS_ORDER = (
    "comprar", "lista", "gasto", "relatorio",
    "semana", "orcamento", "lembretes", "ajuda",
    "cupom", "texto",
)


def help_commands_keyboard(show_back=False, context="start"):
    """Botões inline — um por comando/função."""
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(row_width=2)
    row = []
    for key in HELP_COMMANDS_ORDER:
        info = COMMAND_HELP[key]
        row.append(InlineKeyboardButton(
            f"{info['icon']} {info['button']}",
            callback_data=f"menu:{key}",
        ))
        if len(row) == 2:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
    if show_back:
        markup.row(InlineKeyboardButton("« Voltar", callback_data="menu_back"))
    return markup


def format_help_overview_html(kind="start"):
    """Tela inicial — só explicações; comandos ficam nos botões."""
    if kind == "ajuda":
        msg = _shell("📖 <b>ThéoOS</b> · Ajuda", "Como usar o bot no Telegram")
        welcome = (
            "Toque nos botões para <b>executar</b> cada função do ThéoOS.\n\n"
            "Também funciona enviando <b>foto de cupom</b>, <b>áudio</b> ou <b>texto</b> "
            "com itens — sem precisar decorar nada."
        )
        msg += _blockquote("📖 <b>Guia interativo</b>", welcome)
    else:
        msg = _shell("🤖 <b>ThéoOS</b> · Assistente familiar", "Organize finanças, lista e cupons")
        welcome = (
            "Fala! Sou o <b>ThéoOS</b> — seu assistente familiar no Telegram.\n\n"
            "Toque nos botões abaixo para <b>usar</b> cada função."
        )
        msg += _blockquote("👋 Olá!", welcome)

    msg += "\n\n<i>👇 Toque em um botão para executar</i>"
    return msg.strip()


def format_help_detail_html(cmd_key, context="start"):
    """Detalhe de um comando — só texto explicativo."""
    info = COMMAND_HELP.get(cmd_key)
    if not info:
        return format_help_overview_html(context)

    kind_label = "Ajuda" if context == "ajuda" else "Assistente"
    msg = _shell(
        f"{info['icon']} <b>ThéoOS</b> · {info['title']}",
        f"{kind_label} · <code>{_esc(info['button'] if info['button'].startswith('/') else info['button'])}</code>",
    )
    msg += _blockquote(f"<b>{_esc(info['title'])}</b>", info["body"])
    msg += "\n\n<i>Toque em outro botão ou « Voltar</i>"
    return msg.strip()


def format_start_html():
    return format_help_overview_html("start")


def format_ajuda_html():
    return format_help_overview_html("ajuda")


def format_ok_html(titulo, detalhe=None):
    msg = f"✅ <b>{_esc(titulo)}</b>\n"
    if detalhe:
        msg += f"{SEP}\n{detalhe}"
    return msg.strip()


def format_erro_html(titulo, detalhe=None):
    msg = f"❌ <b>{_esc(titulo)}</b>\n"
    if detalhe:
        msg += f"{SEP}\n{detalhe}"
    return msg.strip()


def format_info_html(titulo, corpo):
    return (_shell(titulo) + corpo).strip()


def format_gasto_ok_html(valor, descricao):
    return format_ok_html(
        "Gasto registrado",
        f"💸 <b>{_money(valor)}</b>\n📝 {_esc(descricao)}",
    )


def format_comprar_ok_html(texto):
    return format_ok_html("Adicionado à lista", f"🛒 {_esc(texto)}")


def format_lista_itens_ok_html(itens, via="lista"):
    titulos = {"lista": "Adicionado à lista", "voz": "Itens via áudio", "texto": "Item adicionado"}
    titulo = titulos.get(via, "Adicionado à lista")
    por_cat = defaultdict(list)
    for i in itens:
        por_cat[i.get("categoria") or "Outros"].append(i)

    msg = _shell(f"✅ <b>ThéoOS</b> · {titulo}")
    for cat, rows in sorted(por_cat.items()):
        body = ""
        for i in rows:
            body += (
                f"  • <b>{_esc(i.get('nome', 'Item'))}</b>\n"
                f"    {_qty(i.get('quantidade', 1))} {_esc(i.get('unidade', 'un'))}\n"
            )
        msg += _blockquote(f"{_cat_icon(cat)} <b>{_esc(cat)}</b>", body) + "\n\n"
    return msg.strip()


def format_relatorio_html(total, ultimos):
    msg = _shell("📊 <b>ThéoOS</b> · Relatório", "Visão geral das finanças")
    msg += f"💰 <b>Total acumulado:</b> {_money(total)}\n\n"

    if ultimos:
        body = ""
        for g in ultimos:
            data = g.data.strftime("%d/%m") if g.data else "—"
            body += f"  • <b>{_esc(g.descricao)}</b>\n    {_money(g.valor)} · <i>{data}</i>\n"
        msg += _blockquote("🕐 <b>Últimos lançamentos</b>", body)
    else:
        msg += "<i>Nenhum lançamento registrado ainda.</i>"
    return msg.strip()


def format_orcamento_html(status_list):
    msg = _shell("📊 <b>ThéoOS</b> · Orçamento do mês", datetime.now().strftime("%m/%Y"))

    alertas = [o for o in status_list if o.get("alerta") or o.get("pct", 0) >= 80]
    ok = [o for o in status_list if o not in alertas]

    if alertas:
        body = ""
        for o in alertas[:8]:
            pct = o.get("pct", 0)
            emoji = "🚨" if pct >= 100 else "⚠️"
            body += (
                f"{emoji} <b>{_esc(o['categoria'])}</b> · <b>{pct:.0f}%</b>\n"
                f"   {_progress_bar(pct)} {_money(o['gasto'])} / {_money(o['limite'])}\n"
            )
            if o.get("meta_economia"):
                economia = max(o["limite"] - o["gasto"], 0)
                body += f"   🎯 Meta: {_money(economia)} de {_money(o['meta_economia'])}\n"
        msg += _blockquote("⚠️ <b>Atenção</b>", body) + "\n\n"

    if ok:
        body = ""
        for o in ok[:8]:
            pct = o.get("pct", 0)
            body += (
                f"✅ <b>{_esc(o['categoria'])}</b> · {pct:.0f}%\n"
                f"   {_progress_bar(pct)} {_money(o['gasto'])} / {_money(o['limite'])}\n"
            )
        msg += _blockquote("✅ <b>Dentro do limite</b>", body)

    msg += "\n\n<i>Configure limites em /config no painel web</i>"
    return msg.strip()


def format_orcamentos_alertas_html(alertas):
    """Alerta automático pós-cupom — várias categorias em uma mensagem."""
    if not alertas:
        return ""
    msg = _shell("⚠️ <b>ThéoOS</b> · Alerta de orçamento", "Categorias acima de 80% no mês")
    body = ""
    for a in alertas:
        pct = a["pct"]
        emoji = "🚨" if pct >= 100 else "⚠️"
        body += (
            f"{emoji} <b>{_esc(a['categoria'])}</b> · <b>{pct:.0f}%</b>\n"
            f"   {_progress_bar(pct)} {_money(a['gasto'])} / {_money(a['limite'])}\n"
        )
    msg += _blockquote("📊 <b>Status</b>", body)
    return msg.strip()


def format_recorrencia_mes_html(quantidade):
    return format_ok_html(
        "Contas fixas geradas",
        f"📅 <b>{quantidade}</b> conta(s) criada(s) para o mês.",
    )


def format_analisando_cupom_html():
    return format_info_html("📸 <b>ThéoOS</b> · Lendo cupom", "Aguarde, estou extraindo os itens…")


def format_nota_duplicada_html():
    return format_erro_html("Cupom já registrado", "Esta nota fiscal já foi processada anteriormente.")


def format_ouvindo_html():
    return format_info_html("👂 <b>ThéoOS</b> · Ouvindo", "Transcrevendo áudio para a lista de compras…")


def format_lista_vazia_html():
    return "✨ <b>ThéoOS</b>\n" + SEP + "\n\n<i>Lista vazia — nada pendente.</i>"


def format_lembretes_ok_html():
    return format_ok_html("Lembretes enviados", "Verifique as mensagens acima neste chat.")


def format_lembretes_vazio_html():
    return format_info_html(
        "⏳ <b>ThéoOS</b> · Lembretes",
        "Nenhuma conta no intervalo configurado.\n\n"
        "<i>Contas vencidas também geram alerta diário.</i>",
    )


def orcamento_keyboard():
    from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
    from theoos.telegram_lista import telegram_url_ok

    markup = InlineKeyboardMarkup()
    url = _web_url("/orcamento")
    if telegram_url_ok(url):
        markup.add(InlineKeyboardButton("📊 Ver orçamento no app", url=url))
    return markup


def format_cupom_html(mercado, itens_lista, total, data_compra=None, riscados=None):
    """Resumo de cupom OCR agrupado por categoria."""
    agora = data_compra or datetime.now()
    data_txt = agora.strftime("%d/%m/%Y") if isinstance(agora, datetime) else str(agora)

    msg = _shell("🛒 <b>ThéoOS</b> · Cupom registrado", f"🏪 {_esc(mercado)} · 📅 {_esc(data_txt)} · {len(itens_lista)} itens")

    por_cat = defaultdict(list)
    for item in itens_lista:
        cat = item.get("categoria") or item.get("Categoria") or "Outros"
        por_cat[cat].append(item)

    for cat, items in sorted(por_cat.items(), key=lambda x: x[0]):
        subtotal = sum(float(i.get("valor_total") or 0) for i in items)
        body = ""
        for item in items:
            nome = item.get("nome_normalizado") or item.get("nome") or "Item"
            bruto = item.get("nome") if item.get("nome_normalizado") else None
            qtd = _qty(item.get("quantidade"))
            un = _esc(item.get("unidade") or "un")
            body += f"  • <b>{_esc(nome)}</b> — {qtd} {un} · {_money(item.get('valor_total', 0))}\n"
            if bruto and bruto.strip().lower() != (nome or "").strip().lower():
                body += f"    <i>↳ cupom: {_esc(bruto)}</i>\n"
        title = f"{_cat_icon(cat)} <b>{_esc(cat)}</b> · {_money(subtotal)}"
        msg += _blockquote(title, body) + "\n\n"

    if riscados:
        body = "\n".join(f"  ☑ <s>{_esc(nome)}</s>" for nome in riscados)
        msg += _blockquote("✅ <b>Baixa na lista</b>", body) + "\n\n"

    msg += f"💰 <b>Total do cupom:</b> {_money(total)}"
    return msg.strip()


def format_contas_vencidas_html(contas, hoje=None):
    """Alerta de contas pendentes com vencimento passado."""
    hoje = hoje or date.today()
    total = sum(c.valor for c in contas)

    msg = _shell(
        "🔴 <b>ThéoOS</b> · Contas vencidas",
        f"⚠️ {len(contas)} conta(s) · {_money(total)} em aberto",
    )

    por_cat = defaultdict(list)
    for c in contas:
        por_cat[c.categoria or "Outros"].append(c)

    for cat, items in sorted(por_cat.items(), key=lambda x: x[0]):
        sub = sum(c.valor for c in items)
        body = ""
        for c in items:
            dias = (hoje - c.data_vencimento).days
            atr = "hoje" if dias == 0 else f"{dias}d atrás"
            body += _conta_card_line(c)
            body += f"   ⏰ venceu <b>{c.data_vencimento.strftime('%d/%m')}</b> · <i>{atr}</i>\n"
        title = f"{_cat_icon(cat)} <b>{_esc(cat)}</b> · {_money(sub)}"
        msg += _blockquote(title, body) + "\n\n"

    msg += f"💰 <b>Total geral:</b> {_money(total)}"
    return msg.strip()


def format_lembrete_contas_html(contas, receber, dias, alvo):
    """Lembrete de contas a pagar/receber em N dias."""
    when = "hoje" if dias == 0 else f"em {dias} dia(s)"
    msg = _shell(
        f"⏳ <b>ThéoOS</b> · Vencimentos {when}",
        f"📅 {alvo.strftime('%d/%m/%Y')}",
    )

    if contas:
        total_pagar = sum(c.valor for c in contas)
        body = ""
        for c in contas:
            body += _conta_card_line(c)
        title = f"💸 <b>A pagar</b> · {_money(total_pagar)} · {len(contas)} conta(s)"
        msg += _blockquote(title, body) + "\n\n"

    if receber:
        total_rec = sum(r.valor for r in receber)
        body = ""
        for r in receber:
            body += _receber_card_line(r)
        title = f"💰 <b>A receber</b> · {_money(total_rec)} · {len(receber)} item(ns)"
        msg += _blockquote(title, body)

    return msg.strip()


def format_variacao_precos_html(alertas, limit=5):
    """Alerta de variação de preços — separa subidas e quedas."""
    alertas = alertas[:limit]
    if not alertas:
        return ""

    subiram = [a for a in alertas if a.get("subiu")]
    baixaram = [a for a in alertas if not a.get("subiu")]

    msg = _shell(
        "📈 <b>ThéoOS</b> · Variação de preços",
        f"🔍 {len(alertas)} produto(s) com mudança relevante",
    )

    if baixaram:
        body = "".join(_linha_variacao(a) for a in baixaram)
        msg += _blockquote("📉 <b>Baixaram</b>", body) + "\n\n"

    if subiram:
        body = "".join(_linha_variacao(a) for a in subiram)
        msg += _blockquote("📈 <b>Subiram</b>", body)

    return msg.strip()


def _linha_variacao(a):
    sinal = "↑" if a.get("subiu") else "↓"
    pct = abs(a.get("pct") or 0)
    return (
        f"  • <b>{_esc(a.get('produto'))}</b> · {sinal} <b>{pct:.0f}%</b>\n"
        f"    {_money(a.get('preco_anterior', 0))} → {_money(a.get('preco_recente', 0))}\n"
    )

