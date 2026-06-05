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

# Força UTF-8 no stdout/stderr para evitar UnicodeEncodeError com emojis no Windows
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
from google import genai
from google.genai import types

from app import app, db, Financas, ItemGasto, ListaCompras, Conta, ContaReceber, Orcamento, Categoria, datetime as app_datetime, timedelta as app_timedelta
from theoos import telegram_lista
from theoos.audit import log_action

load_dotenv()

TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
bot = telebot.TeleBot(TOKEN)

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
NOME_MODELO = 'gemini-2.5-flash'

CATEGORIAS = "'Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros'"

# Estados conversacionais (adicionar item / sugerir melhoria)
_user_states = {}


# ── ALERTAS ───────────────────────────────────────────────────────────────────

def alertar_contas_vencendo():
    from theoos.db_migrate import get_setting
    from theoos import recurring

    with app.app_context():
        days_str = get_setting(db, "reminder_days", "2") or "2"
        enviado = False
        for part in days_str.split(","):
            part = part.strip()
            if not part.isdigit():
                continue
            dias = int(part)
            contas = recurring.contas_due_for_reminder(db, Conta, dias)
            if not contas:
                continue
            alvo = date.today() + app_timedelta(days=dias)
            total = sum(c.valor for c in contas)
            when = "hoje" if dias == 0 else f"em {dias} dia(s)"
            msg = f"⏳ *ThéoOS — Contas {when}* ({alvo.strftime('%d/%m/%Y')})\n\n"
            for c in contas:
                msg += f"• {c.nome} ({c.categoria}): R$ {c.valor:.2f}\n"
            msg += f"\n💰 *Total:* R$ {total:.2f}"
            try:
                bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="Markdown")
                enviado = True
            except Exception as e:
                print(f"Erro alerta contas: {e}")
        return enviado


def alertar_variacao_precos():
    from theoos import insights

    with app.app_context():
        alertas = insights.price_spike_alerts(db, ItemGasto, Financas, min_pct=12.0)
        if not alertas:
            return
        msg = "📈 *ThéoOS — Variação de preços*\n\n"
        for a in alertas[:5]:
            sinal = "↑" if a["subiu"] else "↓"
            msg += (
                f"• {a['produto']}: {sinal} {abs(a['pct']):.0f}% "
                f"(R$ {a['preco_anterior']:.2f} → R$ {a['preco_recente']:.2f})\n"
            )
        try:
            bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Erro alerta preços: {e}")


def verificar_orcamentos(categorias):
    """Envia alerta no Telegram se alguma categoria atingiu ≥80% do orçamento mensal."""
    hoje = date.today()
    primeiro_dia = date(hoje.year, hoje.month, 1)
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
                emoji = "🚨" if pct >= 100 else "⚠️"
                msg = (f"{emoji} *Alerta de Orçamento — {cat}*\n"
                       f"_{pct:.0f}% usado este mês_\n"
                       f"R$ {gasto:.2f} de R$ {orc.limite_mensal:.2f}")
                try:
                    bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="Markdown")
                except Exception as e:
                    print(f"Erro alerta orçamento: {e}")


def _scheduler_loop():
    ultimo_diario = None
    ultimo_mes = None
    while True:
        agora = datetime.now()
        hoje = agora.date()
        if agora.hour == 10 and agora.minute == 0 and ultimo_diario != hoje:
            ultimo_diario = hoje
            alertar_contas_vencendo()
            alertar_variacao_precos()
        if agora.day == 1 and agora.hour == 8 and ultimo_mes != (hoje.year, hoje.month):
            ultimo_mes = (hoje.year, hoje.month)
            with app.app_context():
                from theoos.recurring import run_monthly_generation
                try:
                    n = run_monthly_generation(db, Conta, ContaReceber)
                    if n and TELEGRAM_CHAT_ID:
                        bot.send_message(
                            TELEGRAM_CHAT_ID,
                            f"📅 *ThéoOS* — {n} conta(s) fixa(s) gerada(s) para o mês.",
                            parse_mode="Markdown",
                        )
                except Exception as e:
                    print(f"Recorrência bot: {e}")
        time.sleep(50)

threading.Thread(target=_scheduler_loop, daemon=True).start()


# ── COMMANDS ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message,
        "Fala! Sou o ThéoOS 🤖\n"
        "• /comprar <item> — adiciona à lista\n"
        "• /lista — ver itens pendentes\n"
        "• /gasto <valor> <desc> — registra gasto manual\n"
        "• /relatorio — resumo financeiro\n"
        "• /semana — contas e receitas (7 dias)\n"
        "• /orcamento — status dos limites do mês\n"
        "Você também pode enviar *foto de cupom* ou *áudio* com itens!")


@bot.message_handler(commands=['comprar'])
def adicionar_item(message):
    texto = message.text.replace("/comprar", "").strip()
    if not texto:
        bot.reply_to(message, "Ex: /comprar Frango 2kg")
        return
    with app.app_context():
        autor = message.from_user.username or message.from_user.first_name or "telegram"
        db.session.add(ListaCompras(item=texto, criado_por=f"telegram:{autor}"))
        db.session.commit()
    bot.reply_to(message, f"✅ _{texto}_ adicionado à lista!", parse_mode="Markdown")


def _enviar_lista_formatada(chat_id):
    try:
        with app.app_context():
            itens = ListaCompras.query.filter_by(status='pendente').order_by(
                ListaCompras.categoria, ListaCompras.item
            ).all()
            total = telegram_lista.calc_total_estimado(itens, ItemGasto, db) if itens else 0
        if not itens:
            bot.send_message(chat_id, "✨ Lista vazia! Nada pendente.", parse_mode="HTML")
            return
        telegram_lista.send_lista_message(bot, chat_id, itens, total_estimado=total)
    except Exception as e:
        print(f"ERRO LISTA TELEGRAM: {e}")
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
        bot.reply_to(message, f"💸 Registrado: R$ {valor:.2f} — {desc}")
    except Exception:
        bot.reply_to(message, "❌ Use: /gasto 10.50 Chocolate")


@bot.message_handler(commands=['semana'])
def cmd_semana(message):
    from theoos import insights

    with app.app_context():
        semana = insights.week_agenda(db, Conta, ContaReceber)
    if not semana["contas"] and not semana["receber"]:
        bot.reply_to(message, "Nada a pagar ou receber nos próximos 7 dias (inclui vencidas).")
        return
    msg = "📅 *ThéoOS — Esta semana*\n\n"
    if semana["contas"]:
        msg += "*A pagar:*\n"
        for c in semana["contas"][:8]:
            msg += f"• {c.nome}: R$ {c.valor:.2f} — {c.data_vencimento.strftime('%d/%m')}\n"
        if len(semana["contas"]) > 8:
            msg += f"_+{len(semana['contas']) - 8} conta(s)_\n"
        msg += f"💸 Total: R$ {semana['total_pagar']:.2f}\n\n"
    if semana["receber"]:
        msg += "*A receber:*\n"
        for r in semana["receber"][:8]:
            msg += f"• {r.nome}: R$ {r.valor:.2f} — {r.data_esperada.strftime('%d/%m')}\n"
        if len(semana["receber"]) > 8:
            msg += f"_+{len(semana['receber']) - 8} receita(s)_\n"
        msg += f"💰 Total: R$ {semana['total_receber']:.2f}"
    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=['orcamento'])
def cmd_orcamento(message):
    from theoos import insights

    with app.app_context():
        status = insights.budget_status(db, Orcamento, ItemGasto, Financas)
    if not status:
        bot.reply_to(message, "Nenhum orçamento definido. Configure em /config no painel web.")
        return
    msg = "📊 *ThéoOS — Orçamento do mês*\n\n"
    for o in status[:10]:
        emoji = "🚨" if o["pct"] >= 100 else ("⚠️" if o["alerta"] else "✅")
        msg += f"{emoji} *{o['categoria']}*: {o['pct']:.0f}% — R$ {o['gasto']:.2f} / R$ {o['limite']:.2f}\n"
        if o.get("meta_economia"):
            economia = max(o["limite"] - o["gasto"], 0)
            msg += f"   _Meta economia: R$ {economia:.2f} de R$ {o['meta_economia']:.2f}_\n"
    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=['relatorio'])
def ver_relatorio(message):
    with app.app_context():
        total = db.session.query(db.func.sum(Financas.valor)).scalar() or 0
        ultimos = Financas.query.order_by(Financas.data.desc()).limit(5).all()
        linhas = "\n".join(f"• {g.descricao}: R$ {g.valor:.2f}" for g in ultimos)
    bot.send_message(message.chat.id,
        f"📊 *RELATÓRIO THÉOOS*\n\n💰 *Total acumulado:* R$ {total:.2f}\n\n*Últimas entradas:*\n{linhas}",
        parse_mode="Markdown")


@bot.message_handler(commands=['id'])
def descobrir_id(message):
    bot.reply_to(message, f"Seu Chat ID é: `{message.chat.id}`", parse_mode="Markdown")


# ── MEDIA HANDLERS ────────────────────────────────────────────────────────────

@bot.message_handler(content_types=['photo'])
def ler_nota_fiscal(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "📸 *Analisando cupom...*", parse_mode="Markdown")
    try:
        # 1. Download da imagem
        file_info = bot.get_file(message.photo[-1].file_id)
        img_bytes = bot.download_file(file_info.file_path)

              # 2. Deduplicação por hash MD5 (com fallback se coluna ainda não existir)
        foto_hash = hashlib.md5(img_bytes).hexdigest()
        try:
            with app.app_context():
                if Financas.query.filter_by(foto_hash=foto_hash).first():
                    bot.send_message(chat_id, "⚠️ Esta nota já foi registrada anteriormente.")
                    return
        except Exception:
            foto_hash = None

        # 3. Lista de compras pendentes para cruzamento
        with app.app_context():
            pendentes = ListaCompras.query.filter_by(status='pendente').all()
            lista_str = ", ".join(f"[ID:{p.id} {p.item}]" for p in pendentes) or "Lista vazia."

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

Retorne SOMENTE JSON puro, sem markdown, sem texto extra:
{{"mercado":"Nome","data":"DD/MM/AAAA","total_nota":0.00,"itens":[{{"nome":"NOME ORIGINAL","nome_normalizado":"Nome Limpo","marca":"Marca ou null","quantidade":1.0,"valor_unitario":0.00,"valor_total":0.00,"categoria":"Supermercado","unidade":"un"}}],"ids_comprados":[]}}
"""
        # Sem response_mime_type — chamadas multimodais não suportam esse parâmetro
        resposta = client.models.generate_content(
            model=NOME_MODELO,
            contents=[prompt, image_part]
        )

        print("🧐 RESPOSTA GEMINI:\n", resposta.text)

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

            msg = f"🛒 *{mercado}*\n\n"
            categorias_compradas = []

            for item in itens_lista:
                cat = item.get("categoria", item.get("Categoria", "Outros"))
                categorias_compradas.append(cat)
                db.session.add(ItemGasto(
                    financa_id=novo_gasto.id,
                    nome=item.get("nome", "Desconhecido"),
                    nome_normalizado=item.get("nome_normalizado"),
                    marca=item.get("marca"),
                    quantidade=float(item.get("quantidade", 1.0)),
                    valor_unitario=float(item.get("valor_unitario", 0.0)),
                    valor_total=float(item.get("valor_total", 0.0)),
                    categoria=cat,
                    unidade=item.get("unidade", "un")
                ))
                msg += f"• {item.get('nome')} × {item.get('quantidade')} — R$ {float(item.get('valor_total', 0)):.2f}\n"


            if ids_riscados:
                msg += "\n✅ *Riscados da lista:*\n"
                for cid in ids_riscados:
                    item_lista = db.session.get(ListaCompras, cid)
                    if item_lista and item_lista.status == 'pendente':
                        item_lista.status = 'comprado'
                        item_lista.marcado = False
                        msg += f"~ {item_lista.item} ~\n"

            db.session.commit()

        msg += f"\n💰 *Total: R$ {total:.2f}*"

        # Telegram tem limite de 4096 caracteres por mensagem
        if len(msg) > 4000:
            msg = msg[:3900] + "\n\n_(lista truncada)_"

        bot.send_message(chat_id, msg, parse_mode="Markdown")
        verificar_orcamentos(categorias_compradas)

    except json.JSONDecodeError as e:
        erro = f"❌ A IA não retornou JSON válido.\nResposta: {resposta.text[:300] if 'resposta' in dir() else 'sem resposta'}"
        print(f"ERRO JSON: {e}")
        bot.send_message(chat_id, erro)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"ERRO FOTO:\n{tb}")
        bot.send_message(chat_id, f"❌ Erro ao processar o cupom:\n`{type(e).__name__}: {str(e)[:200]}`", parse_mode="Markdown")


@bot.message_handler(content_types=['voice'])
def processar_voz(message):
    bot.reply_to(message, "👂 *Ouvindo...*", parse_mode="Markdown")
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
            linhas = "\n".join(f"• {i['quantidade']} {i['unidade']} de {i['nome']}" for i in novos_itens)
            bot.reply_to(message, f"✅ *Adicionados via voz:*\n{linhas}", parse_mode="Markdown")
        else:
            bot.reply_to(message, "🤔 Não entendi os itens. Tente novamente.")

    except Exception as e:
        print(f"ERRO VOZ: {e}")
        bot.reply_to(message, "❌ Erro ao processar áudio.")


def _actor_telegram(message):
    u = message.from_user
    return f"telegram:{u.username or u.first_name or 'user'}"


def _adicionar_item_telegram(chat_id, texto, actor):
    texto = (texto or "").strip()
    if not texto:
        bot.send_message(chat_id, "❌ Informe o nome do item (ex: Leite 2 un).")
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
            bot.send_message(chat_id, "🤔 Não entendi o item. Tente de novo (ex: Pão 2 un).")
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
        linhas = "\n".join(
            f"• {i.get('quantidade', 1)} {i.get('unidade', 'un')} — {i['nome']}"
            for i in novos_itens
        )
        bot.send_message(chat_id, f"✅ <b>Adicionado à lista:</b>\n{linhas}", parse_mode="HTML")
        return True
    except Exception as e:
        print(f"ERRO ADD LISTA: {e}")
        bot.send_message(chat_id, "❌ Erro ao adicionar item.")
        return False


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("lista_"))
def callback_lista(call):
    chat_id = call.message.chat.id
    data = call.data

    try:
        if data == "lista_add":
            _user_states[chat_id] = "adding_item"
            bot.answer_callback_query(call.id)
            bot.send_message(
                chat_id,
                "➕ <b>Adicionar item</b>\n\nDigite o produto (ex: <i>Leite 2 un</i> ou <i>Frango 1 kg</i>).",
                parse_mode="HTML",
            )
            return

        if data == "lista_melhoria":
            _user_states[chat_id] = "melhoria"
            bot.answer_callback_query(call.id)
            bot.send_message(
                chat_id,
                "💡 <b>Sugerir melhoria</b>\n\nDescreva o que podemos melhorar no ThéoOS:",
                parse_mode="HTML",
            )
            return

        if data == "lista_riscar_menu":
            with app.app_context():
                itens = ListaCompras.query.filter_by(status="pendente").order_by(
                    ListaCompras.categoria, ListaCompras.item
                ).all()
            bot.answer_callback_query(call.id)
            if not itens:
                bot.send_message(chat_id, "✨ Nenhum item pendente para riscar.")
                return
            texto = "✅ <b>Toque para riscar ou desmarcar</b>\n<i>A baixa financeira só ocorre ao processar o cupom no app.</i>"
            bot.send_message(
                chat_id,
                texto,
                parse_mode="HTML",
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
            bot.send_message(
                chat_id,
                f"🌐 <b>Painel ThéoOS</b>\n\nAbra no navegador:\n<code>{url}</code>\n\n"
                "<i>Dica: defina THEOOS_WEB_URL no .env com o IP da rede "
                "(ex: http://192.168.0.10:5000) para botão direto no celular.</i>",
                parse_mode="HTML",
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
                    "✨ Lista vazia! Nada pendente.",
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
        print(f"ERRO CALLBACK LISTA: {e}")
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
        bot.reply_to(message, "❌ Descreva a melhoria sugerida.")
        return
    actor = _actor_telegram(message)
    with app.app_context():
        log_action(db, "sugestao", "melhoria", detail=texto[:500], actor=actor)
    bot.reply_to(
        message,
        "💡 Obrigado! Sua sugestão foi registrada e será analisada.",
        parse_mode="HTML",
    )


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
            bot.reply_to(message,
                f"✅ *{i['quantidade']} {i['unidade']}* de *{i['nome']}* adicionado!",
                parse_mode="Markdown")
        else:
            bot.reply_to(message, "🤔 Não entendi o que quer comprar.")

    except Exception as e:
        print(f"ERRO TEXTO: {e}")
        bot.reply_to(message, "❌ Erro ao processar a mensagem.")


if __name__ == '__main__':
    print("ThéoOS Bot online...")
    while True:
        try:
            bot.polling(non_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"Erro no polling do bot (reiniciando em 5 segundos): {e}")
            time.sleep(5)
