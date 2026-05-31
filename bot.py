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

from app import app, db, Financas, ItemGasto, ListaCompras, Conta, Orcamento, Categoria, datetime as app_datetime, timedelta as app_timedelta

load_dotenv()

TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
bot = telebot.TeleBot(TOKEN)

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
NOME_MODELO = 'gemini-2.5-flash'

CATEGORIAS = "'Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros'"


# ── ALERTAS ───────────────────────────────────────────────────────────────────

def alertar_contas_vencendo():
    with app.app_context():
        alvo = date.today() + app_timedelta(days=2)
        contas = Conta.query.filter_by(status='pendente', data_vencimento=alvo).all()
        if not contas:
            return
        total = sum(c.valor for c in contas)
        if len(contas) == 1:
            msg = f"⏳ *ALERTA DE VENCIMENTO EM 2 DIAS!*\n\n*Conta a vencer em {alvo.strftime('%d/%m/%Y')}:*\n"
        else:
            msg = f"⏳ *ALERTA DE VENCIMENTO EM 2 DIAS!*\n\n*Contas a vencer em {alvo.strftime('%d/%m/%Y')}:*\n"
            
        for c in contas:
            msg += f"• {c.nome} ({c.categoria}): R$ {c.valor:.2f}\n"
        msg += f"\n💰 *Total do dia:* R$ {total:.2f}"
        try:
            bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Erro alerta contas vencendo: {e}")


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
    ultimo_alerta = None
    while True:
        agora = datetime.now()
        hoje = agora.date()
        if agora.hour == 10 and agora.minute == 0 and ultimo_alerta != hoje:
            ultimo_alerta = hoje
            alertar_contas_vencendo()
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
        "Você também pode enviar *foto de cupom* ou *áudio* com itens!")


@bot.message_handler(commands=['comprar'])
def adicionar_item(message):
    texto = message.text.replace("/comprar", "").strip()
    if not texto:
        bot.reply_to(message, "Ex: /comprar Frango 2kg")
        return
    with app.app_context():
        db.session.add(ListaCompras(item=texto))
        db.session.commit()
    bot.reply_to(message, f"✅ _{texto}_ adicionado à lista!", parse_mode="Markdown")


@bot.message_handler(commands=['lista'])
def ver_lista(message):
    with app.app_context():
        itens = ListaCompras.query.filter_by(status='pendente').all()
    if not itens:
        bot.reply_to(message, "A lista está vazia! 🎉")
        return
    linhas = "\n".join(f"• {i.quantidade} {i.unidade} — {i.item}" for i in itens)
    bot.reply_to(message, f"🛒 *Lista de compras:*\n\n{linhas}", parse_mode="Markdown")


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


@bot.message_handler(func=lambda m: not m.text.startswith('/'))
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
