import sys
import json
import os
import io
import hashlib
import traceback
import threading
import time
from datetime import datetime, date
import telebot

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
from google import genai
from google.genai import types

from app import app, db, Financas, ItemGasto, ListaCompras, Conta, ContaReceber, Orcamento, Categoria, Produto
from datetime import datetime, timedelta
from theoos import telegram_lista
from theoos import telegram_format
from theoos.audit import log_action
from theoos.logging_setup import configure as configure_logging, get_logger

load_dotenv()
configure_logging()
log = get_logger(__name__)

TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
bot = telebot.TeleBot(TOKEN)

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
NOME_MODELO = 'gemini-2.5-flash'

CATEGORIAS = "'Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros'"

# Estados conversacionais (adicionar item / sugerir melhoria)
_user_states = {}


def _html_send(chat_id, text, **kwargs):
    kwargs.setdefault("parse_mode", "HTML")
    return bot.send_message(chat_id, text, **kwargs)


def _html_reply(message, text, **kwargs):
    kwargs.setdefault("parse_mode", "HTML")
    return bot.reply_to(message, text, **kwargs)


# ── ALERTAS ───────────────────────────────────────────────────────────────────

REMINDER_HOUR = 10
DEFAULT_REMINDER_DAYS = "0,1,2,7"


def _load_reminder_last_sent():
    from theoos.db_migrate import get_setting

    with app.app_context():
        raw = get_setting(db, "reminder_last_sent", "")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _save_reminder_last_sent(d):
    from theoos.db_migrate import set_setting

    with app.app_context():
        set_setting(db, "reminder_last_sent", d.isoformat())


def _daily_reminder_due(ultimo_diario, agora):
    """True se ainda não enviou hoje e já passou das REMINDER_HOUR horas."""
    hoje = agora.date()
    if ultimo_diario == hoje:
        return False
    return agora.hour >= REMINDER_HOUR


def alertar_contas_vencendo():
    from theoos.db_migrate import get_setting
    from theoos import recurring

    if not TELEGRAM_CHAT_ID:
        log.warning("Alerta contas: TELEGRAM_CHAT_ID não configurado.")
        return False

    with app.app_context():
        days_str = get_setting(db, "reminder_days", DEFAULT_REMINDER_DAYS) or DEFAULT_REMINDER_DAYS
        days_list = recurring.parse_reminder_days(days_str, DEFAULT_REMINDER_DAYS)
        hoje = date.today()
        enviado = False

        vencidas = recurring.contas_overdue(db, Conta)
        if vencidas:
            msg = telegram_format.format_contas_vencidas_html(vencidas, hoje=hoje)
            try:
                _html_send(TELEGRAM_CHAT_ID, msg, disable_web_page_preview=True)
                enviado = True
            except Exception as e:
                log.exception("Erro alerta contas vencidas: %s", e)

        for dias in days_list:
            contas = recurring.contas_due_for_reminder(db, Conta, dias)
            receber = recurring.receber_due_for_reminder(db, ContaReceber, dias)
            if not contas and not receber:
                continue
            alvo = hoje + timedelta(days=dias)
            msg = telegram_format.format_lembrete_contas_html(contas, receber, dias, alvo)
            try:
                _html_send(TELEGRAM_CHAT_ID, msg, disable_web_page_preview=True)
                enviado = True
            except Exception as e:
                log.exception("Erro alerta contas: %s", e)
        return enviado


def alertar_variacao_precos():
    from theoos import insights

    with app.app_context():
        alertas = insights.price_spike_alerts(db, ItemGasto, Financas, min_pct=12.0)
        if not alertas:
            return
        msg = telegram_format.format_variacao_precos_html(alertas)
        try:
            _html_send(TELEGRAM_CHAT_ID, msg, disable_web_page_preview=True)
        except Exception as e:
            log.exception("Erro alerta preços: %s", e)


def verificar_orcamentos(categorias):
    """Envia alerta no Telegram se alguma categoria atingiu ≥80% do orçamento mensal."""
    hoje = date.today()
    primeiro_dia = date(hoje.year, hoje.month, 1)
    alertas = []
    for cat in set(categorias):
        with app.app_context():
            orc = Orcamento.query.filter_by(categoria=cat).first()
            if not orc:
                continue
            gasto = db.session.query(db.func.sum(ItemGasto.valor_total))\
                .join(Financas)\
                .filter(ItemGasto.categoria == cat, Financas.data >= primeiro_dia)\
                .scalar() or 0
            pct = (gasto / orc.limite_mensal) * 100
            if pct >= 80:
                alertas.append({
                    "categoria": cat,
                    "pct": pct,
                    "gasto": gasto,
                    "limite": orc.limite_mensal,
                })
    if not alertas or not TELEGRAM_CHAT_ID:
        return
    msg = telegram_format.format_orcamentos_alertas_html(alertas)
    try:
        _html_send(TELEGRAM_CHAT_ID, msg, disable_web_page_preview=True)
    except Exception as e:
        log.exception("Erro alerta orçamento: %s", e)


def _run_daily_alerts():
    alertar_contas_vencendo()
    alertar_variacao_precos()
    _save_reminder_last_sent(date.today())


def _scheduler_loop():
    ultimo_diario = _load_reminder_last_sent()
    ultimo_mes = None
    while True:
        agora = datetime.now()
        hoje = agora.date()
        if _daily_reminder_due(ultimo_diario, agora):
            ultimo_diario = hoje
            _run_daily_alerts()
        if agora.day == 1 and agora.hour == 8 and ultimo_mes != (hoje.year, hoje.month):
            ultimo_mes = (hoje.year, hoje.month)
            with app.app_context():
                from theoos.recurring import run_monthly_generation
                try:
                    n = run_monthly_generation(db, Conta, ContaReceber)
                    if n and TELEGRAM_CHAT_ID:
                        _html_send(
                            TELEGRAM_CHAT_ID,
                            telegram_format.format_recorrencia_mes_html(n),
                        )
                except Exception as e:
                    log.exception("Recorrência bot: %s", e)
        time.sleep(50)

threading.Thread(target=_scheduler_loop, daemon=True).start()


def _catch_up_reminders_on_start():
    """Se o bot subir depois das 10h, envia lembretes do dia que ainda não foram."""
    time.sleep(5)
    ultimo = _load_reminder_last_sent()
    if _daily_reminder_due(ultimo, datetime.now()):
        log.info("ThéoOS: lembretes do dia em atraso — enviando agora...")
        _run_daily_alerts()


threading.Thread(target=_catch_up_reminders_on_start, daemon=True).start()


# ── COMMANDS ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=['start'])
def start(message):
    _html_reply(
        message,
        telegram_format.format_start_html(),
        reply_markup=telegram_format.help_commands_keyboard(context="start"),
        disable_web_page_preview=True,
    )


@bot.message_handler(commands=['ajuda', 'help'])
def cmd_ajuda(message):
    _html_reply(
        message,
        telegram_format.format_ajuda_html(),
        reply_markup=telegram_format.help_commands_keyboard(context="ajuda"),
        disable_web_page_preview=True,
    )


@bot.message_handler(commands=['comprar'])
def adicionar_item(message):
    texto = message.text.replace("/comprar", "").strip()
    if not texto:
        _html_reply(message, telegram_format.format_erro_html("Uso incorreto", "Ex: <code>/comprar Frango 2kg</code>"))
        return
    with app.app_context():
        autor = message.from_user.username or message.from_user.first_name or "telegram"
        db.session.add(ListaCompras(item=texto, criado_por=f"telegram:{autor}"))
        db.session.commit()
    _html_reply(message, telegram_format.format_comprar_ok_html(texto))


def _enviar_lista_formatada(chat_id):
    try:
        with app.app_context():
            itens = ListaCompras.query.filter_by(status='pendente').order_by(
                ListaCompras.categoria, ListaCompras.item
            ).all()
            total = telegram_lista.calc_total_estimado(itens, ItemGasto, db) if itens else 0
        if not itens:
            _html_send(chat_id, telegram_format.format_lista_vazia_html())
            return
        telegram_lista.send_lista_message(bot, chat_id, itens, total_estimado=total)
    except Exception as e:
        log.exception("ERRO LISTA TELEGRAM: %s", e)
        bot.send_message(chat_id, "❌ Erro ao enviar a lista. Tente novamente em instantes.")


@bot.message_handler(commands=['lista'])
def ver_lista(message):
    _enviar_lista_formatada(message.chat.id)


@bot.message_handler(commands=['gasto'])
def registrar_gasto(message):
    texto = message.text.replace("/gasto", "").strip()
    try:
        partes = texto.split(" ", 1)
        valor = float(partes[0].replace(",", "."))
        desc = partes[1] if len(partes) > 1 else "Gasto avulso"
        with app.app_context():
            db.session.add(Financas(valor=valor, descricao=desc))
            db.session.commit()
        _html_reply(message, telegram_format.format_gasto_ok_html(valor, desc))
    except Exception:
        _html_reply(message, telegram_format.format_erro_html("Uso incorreto", "Ex: <code>/gasto 10.50 Chocolate</code>"))


@bot.message_handler(commands=['semana'])
def cmd_semana(message):
    _enviar_semana(message.chat.id, reply_to=message.message_id)


def _enviar_semana(chat_id, reply_to=None, edit_message_id=None):
    from theoos import insights

    with app.app_context():
        semana = insights.week_agenda(db, Conta, ContaReceber)

    if not semana["contas"] and not semana["receber"]:
        texto = "✨ Nada a pagar ou receber nos próximos 7 dias (inclui vencidas)."
        if edit_message_id:
            bot.edit_message_text(texto, chat_id, edit_message_id)
        elif reply_to:
            bot.send_message(chat_id, texto, reply_to_message_id=reply_to)
        else:
            bot.send_message(chat_id, texto)
        return

    msg = telegram_format.format_semana_html(semana)
    markup = telegram_format.semana_keyboard()
    if len(msg) > 4000:
        msg = msg[:3900] + "\n\n<i>(agenda truncada)</i>"

    kwargs = dict(parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
    if edit_message_id:
        bot.edit_message_text(msg, chat_id, edit_message_id, **kwargs)
    elif reply_to:
        bot.send_message(chat_id, msg, reply_to_message_id=reply_to, **kwargs)
    else:
        bot.send_message(chat_id, msg, **kwargs)


@bot.callback_query_handler(func=lambda c: c.data == "semana_refresh")
def callback_semana_refresh(call):
    bot.answer_callback_query(call.id, "Atualizando agenda…")
    _enviar_semana(call.message.chat.id, edit_message_id=call.message.message_id)


def _enviar_orcamento(chat_id, reply_to=None):
    from theoos import insights

    with app.app_context():
        status = insights.budget_status(db, Orcamento, ItemGasto, Financas)
    if not status:
        msg = telegram_format.format_info_html(
            "📊 <b>ThéoOS</b> · Orçamento",
            "Nenhum limite definido.\n\nConfigure em <b>/config</b> no painel web.",
        )
        _html_send(chat_id, msg, reply_to_message_id=reply_to)
        return
    msg = telegram_format.format_orcamento_html(status)
    kwargs = dict(
        parse_mode="HTML",
        reply_markup=telegram_format.orcamento_keyboard(),
        disable_web_page_preview=True,
    )
    if reply_to:
        bot.send_message(chat_id, msg, reply_to_message_id=reply_to, **kwargs)
    else:
        bot.send_message(chat_id, msg, **kwargs)


def _enviar_relatorio(chat_id, reply_to=None):
    with app.app_context():
        total = db.session.query(db.func.sum(Financas.valor)).scalar() or 0
        ultimos = Financas.query.order_by(Financas.data.desc()).limit(5).all()
    msg = telegram_format.format_relatorio_html(total, ultimos)
    _html_send(chat_id, msg, reply_to_message_id=reply_to)


def _enviar_lembretes(chat_id, reply_to=None):
    if alertar_contas_vencendo():
        msg = telegram_format.format_lembretes_ok_html()
    else:
        msg = telegram_format.format_lembretes_vazio_html()
    _html_send(chat_id, msg, reply_to_message_id=reply_to)


def _executar_menu_acao(chat_id, cmd_key):
    """Executa a ação real de cada botão do menu /start e /ajuda."""
    if cmd_key == "lista":
        _enviar_lista_formatada(chat_id)
    elif cmd_key == "semana":
        _enviar_semana(chat_id)
    elif cmd_key == "orcamento":
        _enviar_orcamento(chat_id)
    elif cmd_key == "relatorio":
        _enviar_relatorio(chat_id)
    elif cmd_key == "lembretes":
        _enviar_lembretes(chat_id)
    elif cmd_key == "comprar":
        _user_states[chat_id] = "adding_item"
        _html_send(
            chat_id,
            telegram_format.format_info_html(
                "➕ <b>Adicionar à lista</b>",
                "Digite o produto (ex: <i>Leite 2 un</i> ou <i>Frango 1 kg</i>).\n\n"
                "Ou use: <code>/comprar Frango 2kg</code>",
            ),
        )
    elif cmd_key == "gasto":
        _html_send(
            chat_id,
            telegram_format.format_info_html(
                "💸 <b>Gasto manual</b>",
                "Registre um gasto avulso:\n"
                "<code>/gasto 10.50 Chocolate</code>\n"
                "<code>/gasto 45.00 Uber</code>",
            ),
        )
    elif cmd_key == "cupom":
        _html_send(chat_id, telegram_format.format_help_detail_html("cupom"))
    elif cmd_key == "texto":
        _html_send(chat_id, telegram_format.format_help_detail_html("texto"))
    elif cmd_key == "ajuda":
        _html_send(
            chat_id,
            telegram_format.format_ajuda_html(),
            reply_markup=telegram_format.help_commands_keyboard(),
            disable_web_page_preview=True,
        )
    else:
        _html_send(chat_id, telegram_format.format_erro_html("Comando desconhecido"))


@bot.callback_query_handler(func=lambda c: c.data and (c.data.startswith("menu:") or c.data.startswith("help_cmd:")))
def callback_menu(call):
    try:
        chat_id = call.message.chat.id
        data = call.data
        if data.startswith("help_cmd:"):
            parts = data.split(":", 2)
            cmd_key = parts[1] if len(parts) > 1 else ""
        else:
            cmd_key = data.split(":", 1)[1]

        info = telegram_format.COMMAND_HELP.get(cmd_key)
        toast = info["button"] if info else cmd_key
        bot.answer_callback_query(call.id, toast)
        _executar_menu_acao(chat_id, cmd_key)
    except Exception as e:
        log.exception("ERRO CALLBACK MENU: %s", e)
        traceback.print_exc()
        bot.answer_callback_query(call.id, "Erro ao processar.", show_alert=True)


@bot.message_handler(commands=['orcamento'])
def cmd_orcamento(message):
    _enviar_orcamento(message.chat.id, reply_to=message.message_id)


@bot.message_handler(commands=['lembretes'])
def cmd_lembretes(message):
    """Dispara lembretes manualmente (teste ou catch-up)."""
    _enviar_lembretes(message.chat.id, reply_to=message.message_id)


@bot.message_handler(commands=['relatorio'])
def ver_relatorio(message):
    _enviar_relatorio(message.chat.id, reply_to=message.message_id)


@bot.message_handler(commands=['id'])
def descobrir_id(message):
    _html_reply(message, f"🆔 Seu Chat ID: <code>{message.chat.id}</code>")


# ── MEDIA HANDLERS ────────────────────────────────────────────────────────────

@bot.message_handler(content_types=['photo'])
def ler_nota_fiscal(message):
    chat_id = message.chat.id
    _html_send(chat_id, telegram_format.format_analisando_cupom_html())
    try:
        # 1. Download da imagem
        file_info = bot.get_file(message.photo[-1].file_id)
        img_bytes = bot.download_file(file_info.file_path)

        try:
            from theoos.image_utils import normalize_image_for_gemini

            img_bytes, _ = normalize_image_for_gemini(img_bytes, "telegram.jpg")
        except Exception as e:
            log.warning("Falha ao normalizar imagem do Telegram: %s", e)

        foto_hash = hashlib.md5(img_bytes).hexdigest()
        try:
            with app.app_context():
                if Financas.query.filter_by(foto_hash=foto_hash).first():
                    _html_send(chat_id, telegram_format.format_nota_duplicada_html())
                    return
        except Exception:
            foto_hash = None

        # 3. Lista de compras pendentes + catálogo de produtos
        with app.app_context():
            from theoos import produtos as produtos_svc
            pendentes = ListaCompras.query.filter_by(status='pendente').all()
            lista_str = ", ".join(f"[ID:{p.id} {p.item}]" for p in pendentes) or "Lista vazia."
            catalog = produtos_svc.build_catalog(db, ItemGasto, Produto)
            catalog_block = produtos_svc.catalog_prompt_block(catalog)

        # Obter categorias do banco de dados
        try:
            with app.app_context():
                cats_db = Categoria.query.all()
                categorias_prompt = ", ".join(f"'{c.nome}'" for c in cats_db)
        except Exception:
            categorias_prompt = "'Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros'"

        # 4. Envia imagem ao Gemini como bytes (compatível com google-genai)
        image_part = types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg')

        prompt = f"""
Analise o cupom fiscal e extraia todos os itens comprados.
Cruze com minha lista de compras pendentes: {lista_str}
Se identificar que um item da lista foi comprado (mesmo com nome diferente), inclua o ID em ids_comprados.

Classifique cada item em UMA categoria do sistema: [{categorias_prompt}]. Escolha a que melhor se adapta.

Para cada item, além de extrair o nome original/bruto impresso no cupom (no campo "nome"), determine e inclua:
1. Um nome simplificado, limpo e padronizado em "nome_normalizado" (ex: se "LEITE UHT INT LIDER 1L", o nome_normalizado será "Leite Integral"; se "LJA PERA", será "Laranja Pera"; se "ARROZ T1 PRATO FINO 5KG", será "Arroz Branco").
2. A marca do produto no campo "marca" (ex: "Lider", "Prato Fino", "Nestlé"). Se não houver marca identificável, retorne null.
3. A unidade de medida do produto no campo "unidade" (use uma destas siglas: "un", "kg", "g", "l", "ml", "Cx"). Se não for evidente, use "un".
{catalog_block.strip()}

Retorne SOMENTE JSON puro, sem markdown, sem texto extra:
{{"mercado":"Nome","data":"DD/MM/AAAA","total_nota":0.00,"itens":[{{"nome":"NOME ORIGINAL","nome_normalizado":"Nome Limpo","marca":"Marca ou null","quantidade":1.0,"valor_unitario":0.00,"valor_total":0.00,"categoria":"Supermercado","unidade":"un"}}],"ids_comprados":[]}}
"""
        # Sem response_mime_type — chamadas multimodais não suportam esse parâmetro
        resposta = client.models.generate_content(
            model=NOME_MODELO,
            contents=[prompt, image_part]
        )

        log.debug("🧐 RESPOSTA GEMINI:\n%s", resposta.text)

        # 5. Parse JSON — remove eventuais marcações de markdown
        texto_limpo = resposta.text.strip()
        if texto_limpo.startswith('```'):
            texto_limpo = texto_limpo.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

        dados = json.loads(texto_limpo)
        mercado = dados.get("mercado", "Desconhecido")
        total = dados.get("total_nota", 0.0)
        itens_lista = dados.get("itens", [])
        ids_riscados = dados.get("ids_comprados", [])

        # 6. Salva no banco
        with app.app_context():
            produtos_svc.normalize_itens_ocr(db, ItemGasto, itens_lista, Produto)

            # Processa e tenta converter a data retornada pela IA (combinando com a hora atual)
            data_str = dados.get('data', '').strip()
            agora = datetime.now()
            data_gasto = agora
            if data_str:
                try:
                    parsed_date = datetime.strptime(data_str, '%d/%m/%Y')
                    data_gasto = datetime.combine(parsed_date.date(), agora.time())
                except ValueError:
                    try:
                        if '-' in data_str:
                            parsed_date = datetime.strptime(data_str, '%Y-%m-%d')
                        else:
                            parsed_date = datetime.strptime(data_str, '%d/%m/%y')
                        data_gasto = datetime.combine(parsed_date.date(), agora.time())
                    except ValueError:
                        pass

            novo_gasto = Financas(valor=total, descricao=f"IA: {mercado}", foto_hash=foto_hash, data=data_gasto)
            db.session.add(novo_gasto)
            db.session.commit()

            categorias_compradas = []
            riscados_nomes = []

            for item in itens_lista:
                cat = item.get("categoria", item.get("Categoria", "Outros"))
                categorias_compradas.append(cat)
                db.session.add(ItemGasto(
                    financa_id=novo_gasto.id,
                    produto_id=item.get("produto_id"),
                    nome=item.get("nome", "Desconhecido"),
                    nome_normalizado=item.get("nome_normalizado"),
                    marca=item.get("marca"),
                    quantidade=float(item.get("quantidade", 1.0)),
                    valor_unitario=float(item.get("valor_unitario", 0.0)),
                    valor_total=float(item.get("valor_total", 0.0)),
                    categoria=cat,
                    unidade=item.get("unidade", "un")
                ))

            if ids_riscados:
                for cid in ids_riscados:
                    item_lista = db.session.get(ListaCompras, cid)
                    if item_lista and item_lista.status == 'pendente':
                        item_lista.status = 'comprado'
                        item_lista.marcado = False
                        riscados_nomes.append(item_lista.item)

            db.session.commit()

        msg = telegram_format.format_cupom_html(
            mercado, itens_lista, total, data_compra=data_gasto, riscados=riscados_nomes or None,
        )

        # Telegram tem limite de 4096 caracteres por mensagem
        if len(msg) > 4000:
            msg = msg[:3900] + "\n\n<i>(lista truncada)</i>"

        _html_send(chat_id, msg, disable_web_page_preview=True)
        verificar_orcamentos(categorias_compradas)

    except json.JSONDecodeError as e:
        erro = f"❌ A IA não retornou JSON válido.\nResposta: {resposta.text[:300] if 'resposta' in dir() else 'sem resposta'}"
        log.exception("ERRO JSON: %s", e)
        bot.send_message(chat_id, erro)
    except Exception as e:
        tb = traceback.format_exc()
        log.error("ERRO FOTO:\n%s", tb)
        _html_send(chat_id, telegram_format.format_erro_html("Erro ao processar cupom", f"<code>{type(e).__name__}: {str(e)[:200]}</code>"))


@bot.message_handler(content_types=['voice'])
def processar_voz(message):
    _html_reply(message, telegram_format.format_ouvindo_html())
    try:
        file_info = bot.get_file(message.voice.file_id)
        audio_part = types.Part.from_bytes(
            data=bot.download_file(file_info.file_path),
            mime_type='audio/ogg'
        )

        prompt = f"""
Extraia itens para lista de compras do áudio.
Para cada item informe: nome, quantidade, unidade e categoria ({CATEGORIAS}).
Retorne JSON: {{"itens":[{{"nome":"Batata","quantidade":2.0,"unidade":"kg","categoria":"Hortifruti"}}]}}
"""
        resposta = client.models.generate_content(
            model=NOME_MODELO,
            contents=[prompt, audio_part],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        novos_itens = json.loads(resposta.text.strip()).get("itens", [])
        if novos_itens:
            with app.app_context():
                for i in novos_itens:
                    db.session.add(ListaCompras(
                        item=i['nome'].capitalize(),
                        quantidade=float(i['quantidade']),
                        unidade=i['unidade'],
                        categoria=i.get('categoria', 'Outros'),
                        status='pendente'
                    ))
                db.session.commit()
            _html_reply(message, telegram_format.format_lista_itens_ok_html(novos_itens, via="voz"))
        else:
            _html_reply(message, telegram_format.format_erro_html("Não entendi", "Tente descrever os itens novamente."))

    except Exception as e:
        log.exception("ERRO VOZ: %s", e)
        _html_reply(message, telegram_format.format_erro_html("Erro ao processar áudio"))


def _actor_telegram(message):
    u = message.from_user
    return f"telegram:{u.username or u.first_name or 'user'}"


def _adicionar_item_telegram(chat_id, texto, actor):
    texto = (texto or "").strip()
    if not texto:
        _html_send(chat_id, telegram_format.format_erro_html("Informe o item", "Ex: <i>Leite 2 un</i>"))
        return False
    try:
        prompt = f"""
O usuário quer adicionar à lista de compras: "{texto}"
Extraia itens com nome, quantidade, unidade e categoria ({CATEGORIAS}).
Retorne JSON: {{"itens":[{{"nome":"Leite","quantidade":2.0,"unidade":"un","categoria":"Supermercado"}}]}}
"""
        resposta = client.models.generate_content(
            model=NOME_MODELO,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        novos_itens = json.loads(resposta.text.strip()).get("itens", [])
        if not novos_itens:
            _html_send(chat_id, telegram_format.format_erro_html("Não entendi", "Ex: <i>Pão 2 un</i>"))
            return False
        with app.app_context():
            for i in novos_itens:
                db.session.add(ListaCompras(
                    item=i["nome"].capitalize(),
                    quantidade=float(i.get("quantidade", 1)),
                    unidade=i.get("unidade", "un"),
                    categoria=i.get("categoria", "Outros"),
                    status="pendente",
                    criado_por=actor,
                ))
            db.session.commit()
        _html_send(chat_id, telegram_format.format_lista_itens_ok_html(novos_itens, via="lista"))
        return True
    except Exception as e:
        log.exception("ERRO ADD LISTA: %s", e)
        _html_send(chat_id, telegram_format.format_erro_html("Erro ao adicionar item"))
        return False


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("lista_"))
def callback_lista(call):
    chat_id = call.message.chat.id
    data = call.data

    try:
        if data == "lista_add":
            _user_states[chat_id] = "adding_item"
            bot.answer_callback_query(call.id)
            _html_send(
                chat_id,
                telegram_format.format_info_html(
                    "➕ <b>Adicionar item</b>",
                    "Digite o produto (ex: <i>Leite 2 un</i> ou <i>Frango 1 kg</i>).",
                ),
            )
            return

        if data == "lista_melhoria":
            _user_states[chat_id] = "melhoria"
            bot.answer_callback_query(call.id)
            _html_send(
                chat_id,
                telegram_format.format_info_html(
                    "💡 <b>Sugerir melhoria</b>",
                    "Descreva o que podemos melhorar no ThéoOS:",
                ),
            )
            return

        if data == "lista_riscar_menu":
            with app.app_context():
                itens = ListaCompras.query.filter_by(status="pendente").order_by(
                    ListaCompras.categoria, ListaCompras.item
                ).all()
            bot.answer_callback_query(call.id)
            if not itens:
                _html_send(chat_id, telegram_format.format_lista_vazia_html())
                return
            texto = (
                telegram_format.format_info_html(
                    "✅ <b>Riscar / desmarcar</b>",
                    "Toque nos itens abaixo.\n<i>A baixa financeira só ocorre ao processar o cupom no app.</i>",
                )
            )
            _html_send(
                chat_id,
                texto,
                reply_markup=telegram_lista.build_riscar_keyboard(itens),
            )
            return

        if data.startswith("lista_toggle:"):
            item_id = int(data.split(":", 1)[1])
            with app.app_context():
                item = db.session.get(ListaCompras, item_id)
                if not item or item.status != "pendente":
                    bot.answer_callback_query(call.id, "Item não encontrado.", show_alert=True)
                    return
                item.marcado = not bool(item.marcado)
                db.session.commit()
                itens = ListaCompras.query.filter_by(status="pendente").order_by(
                    ListaCompras.categoria, ListaCompras.item
                ).all()
            estado = "riscado" if item.marcado else "desmarcado"
            bot.answer_callback_query(call.id, f"{item.item}: {estado}")
            try:
                bot.edit_message_reply_markup(
                    chat_id,
                    call.message.message_id,
                    reply_markup=telegram_lista.build_riscar_keyboard(itens),
                )
            except Exception:
                pass
            return

        if data == "lista_open":
            url = telegram_lista.web_lista_url()
            bot.answer_callback_query(call.id)
            _html_send(
                chat_id,
                telegram_format.format_info_html(
                    "🌐 <b>Painel ThéoOS</b>",
                    f"Abra no navegador:\n<code>{url}</code>\n\n"
                    "<i>Dica: defina THEOOS_WEB_URL no .env com o IP da rede "
                    "(ex: http://192.168.0.10:5000) para botão direto no celular.</i>",
                ),
            )
            return

        if data == "lista_refresh":
            bot.answer_callback_query(call.id, "Atualizando lista...")
            with app.app_context():
                itens = ListaCompras.query.filter_by(status="pendente").order_by(
                    ListaCompras.categoria, ListaCompras.item
                ).all()
                total = telegram_lista.calc_total_estimado(itens, ItemGasto, db) if itens else 0
            if not itens:
                bot.edit_message_text(
                    telegram_format.format_lista_vazia_html(),
                    chat_id,
                    call.message.message_id,
                    parse_mode="HTML",
                )
                return
            texto = telegram_lista.format_lista_html(itens, total_estimado=total)
            if len(texto) > 4000:
                texto = texto[:3900] + "\n\n<i>(lista truncada)</i>"
            bot.edit_message_text(
                texto,
                chat_id,
                call.message.message_id,
                parse_mode="HTML",
                reply_markup=telegram_lista.build_action_keyboard(),
                disable_web_page_preview=True,
            )
    except Exception as e:
        log.exception("ERRO CALLBACK LISTA: %s", e)
        bot.answer_callback_query(call.id, "Erro ao processar.", show_alert=True)


@bot.message_handler(func=lambda m: m.text and _user_states.get(m.chat.id) == "adding_item")
def handle_lista_add_text(message):
    _user_states.pop(message.chat.id, None)
    actor = _actor_telegram(message)
    ok = _adicionar_item_telegram(message.chat.id, message.text, actor)
    if ok:
        _enviar_lista_formatada(message.chat.id)


@bot.message_handler(func=lambda m: m.text and _user_states.get(m.chat.id) == "melhoria")
def handle_melhoria_text(message):
    _user_states.pop(message.chat.id, None)
    texto = (message.text or "").strip()
    if not texto:
        _html_reply(message, telegram_format.format_erro_html("Sugestão vazia", "Descreva a melhoria desejada."))
        return
    actor = _actor_telegram(message)
    with app.app_context():
        log_action(db, "sugestao", "melhoria", detail=texto[:500], actor=actor)
    _html_reply(message, telegram_format.format_ok_html(
        "Sugestão registrada",
        "💡 Obrigado! Sua ideia será analisada.",
    ))


@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def processar_texto(message):
    try:
        prompt = f"""
O usuário enviou: "{message.text}"
Extraia itens para lista de compras com nome, quantidade, unidade e categoria ({CATEGORIAS}).
Retorne JSON: {{"itens":[{{"nome":"Batata","quantidade":2.0,"unidade":"kg","categoria":"Hortifruti"}}]}}
"""
        resposta = client.models.generate_content(
            model=NOME_MODELO,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        novos_itens = json.loads(resposta.text.strip()).get("itens", [])
        if novos_itens:
            with app.app_context():
                for i in novos_itens:
                    db.session.add(ListaCompras(
                        item=i['nome'].capitalize(),
                        quantidade=float(i['quantidade']),
                        unidade=i['unidade'],
                        categoria=i.get('categoria', 'Outros'),
                        status='pendente'
                    ))
                db.session.commit()
            i = novos_itens[0]
            _html_reply(message, telegram_format.format_lista_itens_ok_html(novos_itens, via="texto"))
        else:
            _html_reply(message, telegram_format.format_erro_html("Não entendi", "Descreva o item que deseja comprar."))

    except Exception as e:
        log.exception("ERRO TEXTO: %s", e)
        _html_reply(message, telegram_format.format_erro_html("Erro ao processar mensagem"))


if __name__ == '__main__':
    import socket
    import telebot.apihelper as apihelper

    _instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _instance_lock.bind(("127.0.0.1", 48721))
        _instance_lock.listen(1)
    except OSError:
        log.warning("Outra instancia do bot ThéoOS ja esta em execucao. Saindo.")
        sys.exit(0)

    apihelper.SESSION_TIME_LIMIT = 600
    log.info("ThéoOS Bot online...")
    backoff = 1
    backoff_max = 60
    while True:
        try:
            bot.polling(non_stop=True, interval=1, timeout=25)
            backoff = 1
        except apihelper.ApiTelegramException as e:
            wait = min(backoff, backoff_max)
            if getattr(e, "result", None) and isinstance(e.result, dict):
                params = e.result.get("parameters", {})
                retry_after = params.get("retry_after")
                if retry_after is not None:
                    wait = max(int(retry_after), 1)
            log.warning("Telegram API erro (aguarda %ss): %s", wait, e)
            time.sleep(wait)
            backoff = min(backoff * 2, backoff_max)
        except Exception as e:
            log.exception("Erro no polling (reiniciando em 5s): %s", e)
            time.sleep(5)
            backoff = 1
