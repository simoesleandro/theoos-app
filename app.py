import os
import io
import csv
import json
import hashlib
from io import StringIO
from datetime import datetime, date, timedelta
from collections import defaultdict
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, request, make_response, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'theoos-secret-2025')

# Gemini client (compartilhado com bot.py)
_gemini_client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
GEMINI_MODEL = 'gemini-2.5-flash'

CATEGORIAS_LISTA = ['Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros']

CATEGORY_CHIP = {
    'Hortifruti': 'chip-success',
    'Supermercado': 'chip-brand',
    'Farmácia': 'chip-danger',
    'Suplemento Alimentar': 'chip-info',
    'Luz': 'chip-warning',
    'Internet': 'chip-info',
    'Condomínio': 'chip-warning',
    'Cartão de Crédito': 'chip-danger',
    'Atividades Théo': 'chip-brand',
    'Veterinário': 'chip-info',
    'Combustível': 'chip-warning',
    'Vacinas': 'chip-info',
    'Contas Fixas': 'chip-neutral',
    'Outros': 'chip-neutral',
}


def chip_class(categoria):
    if not categoria:
        return 'chip-neutral'
    return CATEGORY_CHIP.get(categoria.strip(), 'chip-neutral')


app.jinja_env.globals['chip_class'] = chip_class

UPLOAD_FOLDER = 'static/uploads/boletos'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///theoos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ── MODELS ────────────────────────────────────────────────────────────────────

class ListaCompras(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Float, default=1.0)
    unidade = db.Column(db.String(20), default='un')
    categoria = db.Column(db.String(50), default='Outros')
    marca = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='pendente')
    marcado = db.Column(db.Boolean, default=False)
    criado_por = db.Column(db.String(50), nullable=True)


class Financas(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    valor = db.Column(db.Float, nullable=False)
    descricao = db.Column(db.String(100), nullable=False)
    data = db.Column(db.DateTime, server_default=db.func.now())
    foto_hash = db.Column(db.String(32), nullable=True)
    foto_path = db.Column(db.String(200), nullable=True)
    tipo = db.Column(db.String(10), nullable=False, server_default='debito', default='debito') # 'credito' ou 'debito'
    criado_por = db.Column(db.String(50), nullable=True)
    itens = db.relationship('ItemGasto', backref='nota', lazy=True)


class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    marca = db.Column(db.String(50), nullable=True)
    unidade = db.Column(db.String(20), default='un')
    categoria = db.Column(db.String(50), default='Outros')
    aliases = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, server_default=db.func.now())


class ItemGasto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    financa_id = db.Column(db.Integer, db.ForeignKey('financas.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=True)
    nome = db.Column(db.String(100), nullable=False)
    nome_normalizado = db.Column(db.String(100), nullable=True)
    marca = db.Column(db.String(50), nullable=True)
    quantidade = db.Column(db.Float, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    valor_total = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(50), default='Outros')
    unidade = db.Column(db.String(20), default='un')
    mercado = db.Column(db.String(80), nullable=True)
    produto = db.relationship('Produto', backref='lancamentos', lazy=True)


class Conta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pendente')
    foto_path = db.Column(db.String(200), nullable=True)
    categoria = db.Column(db.String(50), nullable=False, default='Outros')
    criado_por = db.Column(db.String(50), nullable=True)


class ContaReceber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_esperada = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pendente') # 'pendente' ou 'recebido'
    foto_path = db.Column(db.String(200), nullable=True)
    categoria = db.Column(db.String(50), nullable=False, default='Outros')
    criado_por = db.Column(db.String(50), nullable=True)


class Orcamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(50), unique=True, nullable=False)
    limite_mensal = db.Column(db.Float, nullable=False)
    meta_economia = db.Column(db.Float, nullable=True)


class Categoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)


with app.app_context():
    db.create_all()
    # Pre-populate Categoria table if empty
    try:
        if not Categoria.query.first():
            default_categories = [
                'Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar',
                'Luz', 'Internet', 'Condomínio', 'Cartão de Crédito',
                'Atividades Théo', 'Veterinário', 'Combustível', 'Vacinas',
                'Contas Fixas', 'Outros'
            ]
            for cat_nome in default_categories:
                db.session.add(Categoria(nome=cat_nome))
            db.session.commit()
    except Exception as e:
        print(f"Erro ao pre-popular categorias: {e}")
    from theoos.db_migrate import run_migrations
    from theoos.recurring import run_monthly_generation
    run_migrations(db)
    try:
        from theoos import produtos as produtos_svc
        produtos_svc.seed_catalog_from_history(db, Produto, ItemGasto)
    except Exception as e:
        print(f"Seed catálogo produtos: {e}")
    try:
        run_monthly_generation(db, Conta, ContaReceber)
    except Exception as e:
        print(f"Recorrência mensal: {e}")
    # Migrations legadas para colunas antigas
    with db.engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE financas ADD COLUMN tipo TEXT DEFAULT 'debito'"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE financas ADD COLUMN foto_hash TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE financas ADD COLUMN foto_path TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('CREATE INDEX IF NOT EXISTS idx_item_gasto_nome ON item_gasto(nome)'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE item_gasto ADD COLUMN nome_normalizado TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE item_gasto ADD COLUMN marca TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE lista_compras ADD COLUMN marca TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE lista_compras ADD COLUMN marcado INTEGER NOT NULL DEFAULT 0'))
            conn.commit()
        except Exception:
            pass

from flask import session as flask_session
from theoos import auth as theoos_auth
from theoos import routes as theoos_routes

theoos_auth.init_app(app, db)
theoos_routes.register(
    app,
    db,
    {
        "ListaCompras": ListaCompras,
        "Financas": Financas,
        "ItemGasto": ItemGasto,
        "Conta": Conta,
        "ContaReceber": ContaReceber,
        "Orcamento": Orcamento,
    },
)


def _actor():
    return flask_session.get("theoos_actor") or "web"


@app.template_filter('dinheiro')
def dinheiro_filter(val):
    if val is None:
        return "R$ 0,00"
    try:
        return f"R$ {float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {val}"

@app.template_filter('numero')
def numero_filter(val, decimals=1):
    if val is None:
        return "0,0"
    try:
        return f"{float(val):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"{val}"


# ── CONTEXT PROCESSOR ─────────────────────────────────────────────────────────

@app.context_processor
def inject_global_data():
    nav_pendentes = ListaCompras.query.filter_by(status='pendente').count()
    try:
        categorias_db = Categoria.query.order_by(Categoria.nome).all()
        categorias_nomes = [c.nome for c in categorias_db]
        if 'Outros' in categorias_nomes:
            categorias_nomes.remove('Outros')
            categorias_nomes.append('Outros')
    except Exception:
        categorias_nomes = ['Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros']
    try:
        from theoos.db_migrate import get_setting
        ui_theme = get_setting(db, 'theme', 'dark')
    except Exception:
        ui_theme = 'dark'
    return dict(
        nav_pendentes=nav_pendentes,
        categorias_sistema=categorias_nomes,
        chip_class=chip_class,
        CATEGORY_CHIP=CATEGORY_CHIP,
        ui_theme=ui_theme,
    )


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    hoje = date.today()
    primeiro_dia = date(hoje.year, hoje.month, 1)
    hoje_dt = datetime.combine(hoje, datetime.min.time())
    primeiro_dia_dt = datetime.combine(primeiro_dia, datetime.min.time())

    # Current month credits and debits
    total_debitos_mes = db.session.query(db.func.sum(Financas.valor)).filter(
        Financas.data >= primeiro_dia_dt,
        Financas.tipo == 'debito'
    ).scalar() or 0.0

    total_creditos_mes = db.session.query(db.func.sum(Financas.valor)).filter(
        Financas.data >= primeiro_dia_dt,
        Financas.tipo == 'credito'
    ).scalar() or 0.0

    saldo_mes = total_creditos_mes - total_debitos_mes

    # Previous month date range
    if hoje.month == 1:
        primeiro_dia_anterior = date(hoje.year - 1, 12, 1)
        ultimo_dia_anterior = date(hoje.year - 1, 12, 31)
    else:
        primeiro_dia_anterior = date(hoje.year, hoje.month - 1, 1)
        ultimo_dia_anterior = primeiro_dia - timedelta(days=1)

    dt_inicio_anterior = datetime.combine(primeiro_dia_anterior, datetime.min.time())
    dt_fim_anterior = datetime.combine(ultimo_dia_anterior, datetime.max.time())

    # Previous month credits and debits
    total_debitos_mes_anterior = db.session.query(db.func.sum(Financas.valor)).filter(
        Financas.tipo == 'debito',
        Financas.data >= dt_inicio_anterior,
        Financas.data <= dt_fim_anterior
    ).scalar() or 0.0

    total_creditos_mes_anterior = db.session.query(db.func.sum(Financas.valor)).filter(
        Financas.tipo == 'credito',
        Financas.data >= dt_inicio_anterior,
        Financas.data <= dt_fim_anterior
    ).scalar() or 0.0

    # Projections
    projecoes = {}
    for dias in [7, 15, 30, 365]:
        dt_limite = hoje + timedelta(days=dias)
        
        receitas_periodo = db.session.query(db.func.sum(ContaReceber.valor)).filter(
            ContaReceber.status == 'pendente',
            ContaReceber.data_esperada <= dt_limite
        ).scalar() or 0.0
        
        despesas_periodo = db.session.query(db.func.sum(Conta.valor)).filter(
            Conta.status == 'pendente',
            Conta.data_vencimento <= dt_limite
        ).scalar() or 0.0
        
        saldo_periodo = receitas_periodo - despesas_periodo
        
        projecoes[dias] = {
            'receitas': receitas_periodo,
            'despesas': despesas_periodo,
            'saldo_periodo': saldo_periodo,
            'saldo_projetado': saldo_mes + saldo_periodo
        }

    pendentes = ListaCompras.query.filter_by(status='pendente').count()
    lista_preview = ListaCompras.query.filter_by(status='pendente').limit(5).all()

    contas_pendentes_count = Conta.query.filter_by(status='pendente').count()

    num_transacoes = Financas.query.filter(Financas.data >= primeiro_dia_dt).count()
    notas = Financas.query.order_by(Financas.data.desc()).limit(5).all()

    # Últimos 30 dias para o gráfico (agrupados por débito e crédito)
    datas_grafico = []
    debitos_agrupados = defaultdict(float)
    creditos_agrupados = defaultdict(float)
    
    for i in range(29, -1, -1):
        dia_str = (hoje - timedelta(days=i)).strftime('%d/%m')
        datas_grafico.append(dia_str)
        debitos_agrupados[dia_str] = 0.0
        creditos_agrupados[dia_str] = 0.0

    for nota in Financas.query.filter(Financas.data >= datetime.combine(hoje - timedelta(days=29), datetime.min.time())).all():
        dia_str = nota.data.strftime('%d/%m')
        if dia_str in debitos_agrupados:
            if nota.tipo == 'credito':
                creditos_agrupados[dia_str] += nota.valor
            else:
                debitos_agrupados[dia_str] += nota.valor

    valores_debitos = [debitos_agrupados[d] for d in datas_grafico]
    valores_creditos = [creditos_agrupados[d] for d in datas_grafico]

    # Categorias do mês atual
    gastos_por_cat = defaultdict(float)
    for item in ItemGasto.query.join(Financas).filter(
        Financas.data >= primeiro_dia_dt,
        Financas.tipo == 'debito'
    ).all():
        gastos_por_cat[item.categoria or 'Outros'] += item.valor_total

    from theoos import insights
    semana = insights.week_agenda(db, Conta, ContaReceber, hoje, days=7)
    orcamento_status = insights.budget_status(db, Orcamento, ItemGasto, Financas)
    alertas_preco = insights.price_spike_alerts(db, ItemGasto, Financas)[:5]
    habitos_sumidos = insights.missing_habit_products(db, ItemGasto, Financas)[:4]

    return render_template('index.html',
        total=total_debitos_mes, # compatibility
        total_debitos_mes=total_debitos_mes,
        total_creditos_mes=total_creditos_mes,
        saldo_mes=saldo_mes,
        total_debitos_mes_anterior=total_debitos_mes_anterior,
        total_creditos_mes_anterior=total_creditos_mes_anterior,
        projecoes=projecoes,
        pendentes=pendentes,
        lista_preview=lista_preview,
        contas_pendentes=contas_pendentes_count,
        num_transacoes=num_transacoes,
        notas=notas,
        datas=datas_grafico,
        valores_debitos=valores_debitos,
        valores_creditos=valores_creditos,
        labels_cat=list(gastos_por_cat.keys()),
        valores_cat=list(gastos_por_cat.values()),
        hoje=hoje,
        today_date=hoje,
        today_str=hoje.strftime('%Y-%m-%d'),
        semana=semana,
        orcamento_status=orcamento_status,
        alertas_preco=alertas_preco,
        habitos_sumidos=habitos_sumidos,
    )


@app.route('/lista')
def lista_compras():
    itens_pendentes = ListaCompras.query.filter_by(status='pendente').all()
    itens_comprados = ListaCompras.query.filter_by(status='comprado').order_by(ListaCompras.id.desc()).limit(20).all()
    
    total_estimado = 0.0
    for item in itens_pendentes:
        # Busca o item correspondente mais recente no histórico de gastos (case-insensitive, nome ou nome_normalizado)
        query = ItemGasto.query.filter(
            db.or_(
                db.func.lower(ItemGasto.nome) == db.func.lower(item.item.strip()),
                db.func.lower(ItemGasto.nome_normalizado) == db.func.lower(item.item.strip())
            )
        )
        if item.marca and item.marca.strip():
            query = query.filter(db.func.lower(ItemGasto.marca) == db.func.lower(item.marca.strip()))
            
        ultimo_gasto = query.order_by(ItemGasto.id.desc()).first()
        
        if ultimo_gasto:
            item.ultimo_preco = ultimo_gasto.valor_unitario
            total_estimado += item.ultimo_preco * item.quantidade
        else:
            item.ultimo_preco = None
            
    # 1. Obter itens do histórico de compras (ItemGasto)
    nome_item_expr = db.case(
        (db.and_(ItemGasto.nome_normalizado != None, ItemGasto.nome_normalizado != ''), ItemGasto.nome_normalizado),
        else_=ItemGasto.nome
    )
    subquery = db.session.query(
        nome_item_expr.label('nome_item'),
        ItemGasto.marca,
        ItemGasto.unidade,
        ItemGasto.categoria,
        db.func.max(ItemGasto.id).label('max_id')
    ).group_by(
        nome_item_expr,
        ItemGasto.marca,
        ItemGasto.unidade,
        ItemGasto.categoria
    ).subquery()

    itens_gasto = db.session.query(
        subquery.c.nome_item,
        subquery.c.marca,
        subquery.c.unidade,
        subquery.c.categoria,
        ItemGasto.valor_unitario
    ).join(ItemGasto, ItemGasto.id == subquery.c.max_id).all()

    # 2. Obter itens da lista de compras (ListaCompras)
    itens_lista = db.session.query(
        ListaCompras.item.label('nome_item'),
        ListaCompras.marca,
        ListaCompras.unidade,
        ListaCompras.categoria
    ).group_by(
        ListaCompras.item,
        ListaCompras.marca,
        ListaCompras.unidade,
        ListaCompras.categoria
    ).all()

    # 3. Mesclar mantendo a unicidade
    produtos_set = set()
    produtos_historico = []
    
    # Adicionar primeiro os do histórico de compras (prioritários)
    for p in itens_gasto:
        key = (p.nome_item.strip().lower(), (p.marca or '').strip().lower(), p.unidade.strip().lower(), p.categoria.strip().lower())
        if key not in produtos_set:
            produtos_set.add(key)
            produtos_historico.append({
                'nome_item': p.nome_item.strip(),
                'marca': p.marca.strip() if p.marca else None,
                'unidade': p.unidade.strip() or 'un',
                'categoria': p.categoria.strip() or 'Supermercado',
                'ultimo_preco': p.valor_unitario
            })
            
    # Adicionar os da lista de compras que não existam no histórico
    for p in itens_lista:
        key = (p.nome_item.strip().lower(), (p.marca or '').strip().lower(), p.unidade.strip().lower(), p.categoria.strip().lower())
        if key not in produtos_set:
            produtos_set.add(key)
            produtos_historico.append({
                'nome_item': p.nome_item.strip(),
                'marca': p.marca.strip() if p.marca else None,
                'unidade': p.unidade.strip() or 'un',
                'categoria': p.categoria.strip() or 'Supermercado',
                'ultimo_preco': None
            })

    from theoos import insights
    cesta_lojas = insights.basket_estimates_by_store(db, ListaCompras, ItemGasto, Financas)

    return render_template('lista.html',
                           itens_pendentes=itens_pendentes,
                           itens_comprados=itens_comprados,
                           total_estimado=total_estimado,
                           produtos_historico=produtos_historico,
                           cesta_lojas=cesta_lojas)


@app.route('/comprado/<int:id>')
def marcar_comprado(id):
    qtd_comprada = float(request.args.get('qtd', 0))
    valor_pago = float(request.args.get('preco', '0').replace(',', '.'))

    item = db.session.get(ListaCompras, id)
    if item:
        if qtd_comprada >= item.quantidade:
            item.status = 'comprado'
            item.marcado = False
        else:
            item.quantidade -= qtd_comprada

        # Cria o registro em Financas e faz o flush para obter o ID gerado
        novo_gasto = Financas(
            valor=valor_pago,
            descricao=f"Compra: {item.item}",
            criado_por=_actor(),
        )
        db.session.add(novo_gasto)
        db.session.flush()

        valor_unitario = valor_pago / qtd_comprada if qtd_comprada > 0 else 0.0
        db.session.add(ItemGasto(
            financa_id=novo_gasto.id,
            nome=item.item,
            quantidade=qtd_comprada,
            valor_unitario=valor_unitario,
            valor_total=valor_pago,
            categoria=item.categoria,
            marca=item.marca,
            unidade=item.unidade,
            mercado=request.args.get('mercado', '').strip() or None,
        ))
        db.session.commit()

    return redirect(url_for('lista_compras'))


@app.route('/relatorios')
def relatorios():
    page = request.args.get('page', 1, type=int)
    paginacao = Financas.query.order_by(Financas.data.desc()).paginate(page=page, per_page=20, error_out=False)
    
    total_geral_debitos = db.session.query(db.func.sum(Financas.valor)).filter(Financas.tipo == 'debito').scalar() or 0.0
    total_geral_creditos = db.session.query(db.func.sum(Financas.valor)).filter(Financas.tipo == 'credito').scalar() or 0.0
    saldo_geral = total_geral_creditos - total_geral_debitos

    gastos_agrupados = defaultdict(float)
    for nota in Financas.query.filter_by(tipo='debito').all():
        gastos_agrupados[nota.data.strftime('%d/%m')] += nota.valor

    gastos_por_cat = defaultdict(float)
    for item in ItemGasto.query.join(Financas).filter(Financas.tipo == 'debito').all():
        gastos_por_cat[item.categoria or 'Outros'] += item.valor_total

    # KPIs Adicionais
    total_debitos_count = Financas.query.filter_by(tipo='debito').count()
    media_gasto = total_geral_debitos / total_debitos_count if total_debitos_count > 0 else 0.0
    maior_compra = db.session.query(db.func.max(Financas.valor)).filter(Financas.tipo == 'debito').scalar() or 0.0
    
    categoria_lider = "Nenhuma"
    if gastos_por_cat:
        categoria_lider = max(gastos_por_cat, key=gastos_por_cat.get)

    from theoos import insights
    variacoes_principais = insights.price_variations(db, ItemGasto, Financas, limit=5)

    # ── ANÁLISE DE VENCIMENTOS ────────────────────────────────────────────────
    hoje_data = date.today()

    # Contas vencidas (status pendente e data de vencimento < hoje)
    contas_vencidas_q = Conta.query.filter(Conta.status == 'pendente', Conta.data_vencimento < hoje_data).all()
    total_vencidas_valor = sum(c.valor for c in contas_vencidas_q)
    total_vencidas_qtd = len(contas_vencidas_q)

    # Contas a vencer (status pendente e data de vencimento >= hoje)
    contas_a_vencer_q = Conta.query.filter(Conta.status == 'pendente', Conta.data_vencimento >= hoje_data).all()
    total_a_vencer_valor = sum(c.valor for c in contas_a_vencer_q)
    total_a_vencer_qtd = len(contas_a_vencer_q)

    # ── FILTRO DE PERÍODO ─────────────────────────────────────────────────────
    periodo_inicio_str = request.args.get('periodo_inicio', '')
    periodo_fim_str = request.args.get('periodo_fim', '')

    try:
        periodo_inicio = datetime.strptime(periodo_inicio_str, '%Y-%m-%d').date() if periodo_inicio_str else hoje_data
    except ValueError:
        periodo_inicio = hoje_data
    try:
        periodo_fim = datetime.strptime(periodo_fim_str, '%Y-%m-%d').date() if periodo_fim_str else hoje_data + timedelta(days=60)
    except ValueError:
        periodo_fim = hoje_data + timedelta(days=60)

    # Contas a pagar no período (pendentes)
    contas_periodo = Conta.query.filter(
        Conta.status == 'pendente',
        Conta.data_vencimento >= periodo_inicio,
        Conta.data_vencimento <= periodo_fim
    ).order_by(Conta.data_vencimento).all()
    soma_pagar_periodo = sum(c.valor for c in contas_periodo)

    # Contas a receber no período (pendentes)
    receber_periodo = ContaReceber.query.filter(
        ContaReceber.status == 'pendente',
        ContaReceber.data_esperada >= periodo_inicio,
        ContaReceber.data_esperada <= periodo_fim
    ).order_by(ContaReceber.data_esperada).all()
    soma_receber_periodo = sum(r.valor for r in receber_periodo)

    saldo_projetado_periodo = soma_receber_periodo - soma_pagar_periodo

    # 1. Agrupamento de despesas previstas (Contas a Pagar no Período) por Categoria
    previsao_categoria_dict = defaultdict(float)
    for c in contas_periodo:
        previsao_categoria_dict[c.categoria] += c.valor
    
    previsao_categoria = sorted(
        [{"categoria": cat, "valor": val} for cat, val in previsao_categoria_dict.items()],
        key=lambda x: x["valor"],
        reverse=True
    )

    # 2. Quadro Comparativo Intermensal (Gasto Real: débitos de Financas)
    comp_inicio_str = request.args.get('comp_inicio', '')
    comp_fim_str = request.args.get('comp_fim', '')
    primeiro_dia_mes = date(hoje_data.year, hoje_data.month, 1)

    try:
        comp_inicio = datetime.strptime(comp_inicio_str, '%Y-%m-%d').date() if comp_inicio_str else primeiro_dia_mes
    except ValueError:
        comp_inicio = primeiro_dia_mes

    try:
        comp_fim = datetime.strptime(comp_fim_str, '%Y-%m-%d').date() if comp_fim_str else hoje_data
    except ValueError:
        comp_fim = hoje_data

    def shift_month(dt, months):
        import calendar
        month = dt.month - 1 + months
        year = dt.year + month // 12
        month = month % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    prev_inicio = shift_month(comp_inicio, -1)
    prev_fim = shift_month(comp_fim, -1)
    next_inicio = shift_month(comp_inicio, 1)
    next_fim = shift_month(comp_fim, 1)

    def get_gastos_periodo(start_date, end_date):
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        total = db.session.query(db.func.sum(Financas.valor)).filter(
            Financas.tipo == 'debito',
            Financas.data >= start_dt,
            Financas.data <= end_dt
        ).scalar() or 0.0
        results = db.session.query(
            ItemGasto.categoria,
            db.func.sum(ItemGasto.valor_total)
        ).join(Financas).filter(
            Financas.tipo == 'debito',
            Financas.data >= start_dt,
            Financas.data <= end_dt
        ).group_by(ItemGasto.categoria).all()
        categorias = {cat: val for cat, val in results if cat}
        return {"total": total, "categorias": categorias}

    comp_atual = get_gastos_periodo(comp_inicio, comp_fim)
    comp_prev = get_gastos_periodo(prev_inicio, prev_fim)
    comp_next = get_gastos_periodo(next_inicio, next_fim)

    comp_total_diff_pct = 0.0
    if comp_prev["total"] > 0:
        comp_total_diff_pct = ((comp_atual["total"] - comp_prev["total"]) / comp_prev["total"]) * 100

    all_cats = set(comp_atual["categorias"].keys()) | set(comp_prev["categorias"].keys()) | set(comp_next["categorias"].keys())
    comparativo_categorias = []
    for cat in all_cats:
        val_prev = comp_prev["categorias"].get(cat, 0.0)
        val_atual = comp_atual["categorias"].get(cat, 0.0)
        val_next = comp_next["categorias"].get(cat, 0.0)
        diff_prev_pct = 0.0
        if val_prev > 0:
            diff_prev_pct = ((val_atual - val_prev) / val_prev) * 100
        comparativo_categorias.append({
            "categoria": cat,
            "valor_prev": val_prev,
            "valor_atual": val_atual,
            "valor_next": val_next,
            "diff_prev_pct": diff_prev_pct
        })
    comparativo_categorias.sort(key=lambda x: x["valor_atual"], reverse=True)

    return render_template('relatorios.html',
        notas=paginacao.items,
        total=total_geral_debitos,
        total_creditos=total_geral_creditos,
        saldo_geral=saldo_geral,
        paginacao=paginacao,
        datas=list(gastos_agrupados.keys()),
        valores=list(gastos_agrupados.values()),
        labels_cat=list(gastos_por_cat.keys()),
        valores_cat=list(gastos_por_cat.values()),
        media_gasto=media_gasto,
        maior_compra=maior_compra,
        categoria_lider=categoria_lider,
        variacoes=variacoes_principais,
        total_vencidas_valor=total_vencidas_valor,
        total_vencidas_qtd=total_vencidas_qtd,
        total_a_vencer_valor=total_a_vencer_valor,
        total_a_vencer_qtd=total_a_vencer_qtd,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        contas_periodo=contas_periodo,
        soma_pagar_periodo=soma_pagar_periodo,
        receber_periodo=receber_periodo,
        soma_receber_periodo=soma_receber_periodo,
        saldo_projetado_periodo=saldo_projetado_periodo,
        previsao_categoria=previsao_categoria,
        comp_inicio=comp_inicio,
        comp_fim=comp_fim,
        comp_prev_inicio=prev_inicio,
        comp_prev_fim=prev_fim,
        comp_next_inicio=next_inicio,
        comp_next_fim=next_fim,
        comp_atual_total=comp_atual["total"],
        comp_prev_total=comp_prev["total"],
        comp_next_total=comp_next["total"],
        comp_total_diff_pct=comp_total_diff_pct,
        comparativo_categorias=comparativo_categorias,
        hoje=hoje_data
    )


@app.route('/relatorios/deletar/<int:id>', methods=['POST'])
def deletar_transacao(id):
    nota = db.session.get(Financas, id)
    if nota:
        if nota.foto_path:
            caminho = os.path.join(app.config['UPLOAD_FOLDER'], nota.foto_path)
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except Exception:
                    pass
        
        # Deleta os itens associados
        ItemGasto.query.filter_by(financa_id=id).delete()
        from theoos import audit
        audit.log_action(db, 'delete', 'Financas', id, nota.descricao, _actor())
        db.session.delete(nota)
        db.session.commit()
        flash('Transação excluída com sucesso!', 'success')
    else:
        flash('Transação não encontrada.', 'danger')
    return redirect(url_for('relatorios'))


@app.route('/pesquisa')
def pesquisa():
    termo = request.args.get('q', '').strip()
    from theoos import insights

    resultados = insights.pesquisa_resultados(db, ItemGasto, Financas, termo) if termo else []
    minmax_unidades = insights.minmax_por_unidade(resultados) if resultados else {}

    # Buscar os itens que mais são gastos (maior soma de valor_total) no banco de dados
    try:
        from sqlalchemy import func, desc
        popular_items_query = db.session.query(
            func.coalesce(ItemGasto.nome_normalizado, ItemGasto.nome).label('nome_item'),
            func.sum(ItemGasto.valor_total).label('total_gasto')
        ).group_by(
            func.coalesce(ItemGasto.nome_normalizado, ItemGasto.nome)
        ).order_by(
            desc('total_gasto')
        ).limit(12).all()
        
        itens_populares = [item.nome_item for item in popular_items_query if item.nome_item and len(item.nome_item) <= 25]
    except Exception as e:
        print(f"Erro ao buscar itens populares: {e}")
        itens_populares = []
        
    # Fallback default items se estiver vazio ou com poucos registros
    fallback_defaults = ['Leite', 'Arroz', 'Feijão', 'Pão de Forma', 'Frango', 'Detergente', 'Café', 'Açúcar']
    for default_item in fallback_defaults:
        if len(itens_populares) >= 8:
            break
        # Case insensitive check
        exists = any(default_item.lower() == item.lower() for item in itens_populares)
        if not exists:
            itens_populares.append(default_item)

    mercado_ranking = (
        insights.market_ranking_global(db, ItemGasto, Financas) if not termo else []
    )
    mercado_produto = (
        insights.market_prices_for_term(db, ItemGasto, Financas, termo) if termo else []
    )
    return render_template(
        "pesquisa.html",
        termo=termo,
        resultados=resultados,
        minmax_unidades=minmax_unidades,
        itens_populares=itens_populares,
        mercado_ranking=mercado_ranking,
        mercado_produto=mercado_produto,
    )


@app.route('/exportar')
def exportar():
    itens = ItemGasto.query.all()
    si = StringIO()
    cw = csv.writer(si, delimiter=';')
    cw.writerow(['Data', 'Mercado', 'Produto', 'Qtd', 'Valor Unitário', 'Valor Total', 'Categoria'])
    for i in itens:
        cw.writerow([
            i.nota.data.strftime('%d/%m/%Y'),
            i.nota.descricao.replace('IA: ', ''),
            i.nome,
            i.quantidade,
            f"{i.valor_unitario:.2f}".replace('.', ','),
            f"{i.valor_total:.2f}".replace('.', ','),
            i.categoria
        ])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=relatorio_theoos.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8-sig"
    return output


@app.route('/contas', methods=['GET', 'POST'])
def contas():
    if request.method == 'POST':
        nome = request.form['nome']
        valor = float(request.form['valor'].replace(',', '.'))
        data_obj = datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
        categoria = request.form['categoria']

        foto_path = None
        if 'foto' in request.files:
            arquivo = request.files['foto']
            if arquivo.filename:
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{arquivo.filename}")
                arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                foto_path = filename

        recorrente = 'recorrente' in request.form
        meses = int(request.form.get('meses', 1)) if recorrente else 1
        if meses < 1:
            meses = 1

        if meses > 1:
            import calendar
            for i in range(meses):
                new_month = data_obj.month - 1 + i
                year = data_obj.year + new_month // 12
                month = new_month % 12 + 1
                day = min(data_obj.day, calendar.monthrange(year, month)[1])
                data_venc = date(year, month, day)
                nome_parcela = nome
                db.session.add(Conta(nome=nome_parcela, valor=valor, data_vencimento=data_venc,
                                     foto_path=foto_path, categoria=categoria))
            db.session.commit()
            flash(f'Conta e suas {meses} parcelas recorrentes cadastradas com sucesso!', 'success')
        else:
            db.session.add(Conta(nome=nome, valor=valor, data_vencimento=data_obj,
                                 foto_path=foto_path, categoria=categoria))
            db.session.commit()
            flash('Conta cadastrada com sucesso!', 'success')
        return redirect(url_for('contas'))

    busca_contas = request.args.get('busca_contas', '').strip()
    pag_contas = request.args.get('pag_contas', 1, type=int)

    query_pendentes = Conta.query.filter_by(status='pendente')
    if busca_contas:
        query_pendentes = query_pendentes.filter(Conta.nome.ilike(f'%{busca_contas}%'))
    query_pendentes = query_pendentes.order_by(Conta.data_vencimento)

    soma_filtrada = db.session.query(db.func.sum(Conta.valor)).filter(Conta.status == 'pendente')
    if busca_contas:
        soma_filtrada = soma_filtrada.filter(Conta.nome.ilike(f'%{busca_contas}%'))
    soma_filtrada = soma_filtrada.scalar() or 0.0

    paginacao_contas = query_pendentes.paginate(page=pag_contas, per_page=30, error_out=False)

    pagas = Conta.query.filter_by(status='pago').order_by(Conta.data_vencimento.desc()).limit(30).all()
    hoje = datetime.now().date()
    return render_template('contas.html',
        contas=paginacao_contas.items,
        paginacao_contas=paginacao_contas,
        busca_contas=busca_contas,
        soma_filtrada=soma_filtrada,
        contas_pagas=pagas,
        hoje=hoje,
        today_date=hoje,
        today_str=hoje.strftime('%Y-%m-%d'))


@app.route('/contas/editar/<int:id>', methods=['POST'])
def editar_conta(id):
    conta = db.session.get(Conta, id)
    if not conta:
        flash('Conta não encontrada.', 'danger')
        return redirect(url_for('contas'))
    
    try:
        nome = request.form['nome']
        valor = float(request.form['valor'].replace(',', '.'))
        data_obj = datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
        categoria = request.form['categoria']

        if 'foto' in request.files:
            arquivo = request.files['foto']
            if arquivo.filename:
                # Remove anterior se houver
                if conta.foto_path:
                    antigo = os.path.join(app.config['UPLOAD_FOLDER'], conta.foto_path)
                    if os.path.exists(antigo):
                        try:
                            os.remove(antigo)
                        except Exception:
                            pass
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{arquivo.filename}")
                arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                conta.foto_path = filename

        if request.form.get('remover_foto') == 'true':
            if conta.foto_path:
                antigo = os.path.join(app.config['UPLOAD_FOLDER'], conta.foto_path)
                if os.path.exists(antigo):
                    try:
                        os.remove(antigo)
                    except Exception:
                        pass
                conta.foto_path = None

        conta.nome = nome
        conta.valor = valor
        conta.data_vencimento = data_obj
        conta.categoria = categoria

        db.session.commit()
        flash('Conta atualizada com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao atualizar conta: {e}', 'danger')
        
    return redirect(url_for('contas'))


@app.route('/contas/deletar/<int:id>', methods=['POST', 'GET'])
def deletar_conta(id):
    conta = db.session.get(Conta, id)
    if conta:
        if conta.foto_path:
            caminho = os.path.join(app.config['UPLOAD_FOLDER'], conta.foto_path)
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except Exception:
                    pass
        db.session.delete(conta)
        db.session.commit()
        flash('Conta excluída com sucesso!', 'success')
    else:
        flash('Conta não encontrada.', 'danger')
    return redirect(url_for('contas'))


@app.route('/pagar_conta/<int:id>')
def pagar_conta(id):
    conta = db.session.get(Conta, id)
    if conta:
        conta.status = 'pago'
        # Copia o foto_path para manter no histórico de despesas
        novo_gasto = Financas(valor=conta.valor, descricao=f"Conta Paga: {conta.nome}", foto_path=conta.foto_path)
        db.session.add(novo_gasto)
        db.session.flush()
        db.session.add(ItemGasto(
            financa_id=novo_gasto.id,
            nome=conta.nome,
            quantidade=1.0,
            valor_unitario=conta.valor,
            valor_total=conta.valor,
            categoria=conta.categoria
        ))
        db.session.commit()
        flash(f'Conta "{conta.nome}" paga com sucesso!', 'success')
    return redirect(url_for('contas'))


@app.route('/receber', methods=['GET', 'POST'])
def receber():
    if request.method == 'POST':
        nome = request.form['nome']
        valor = float(request.form['valor'].replace(',', '.'))
        data_obj = datetime.strptime(request.form['data_esperada'], '%Y-%m-%d').date()
        categoria = request.form['categoria']

        foto_path = None
        if 'foto' in request.files:
            arquivo = request.files['foto']
            if arquivo.filename:
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_rec_{arquivo.filename}")
                arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                foto_path = filename

        recorrente = 'recorrente' in request.form
        meses = int(request.form.get('meses', 1)) if recorrente else 1
        if meses < 1:
            meses = 1

        if meses > 1:
            import calendar
            for i in range(meses):
                new_month = data_obj.month - 1 + i
                year = data_obj.year + new_month // 12
                month = new_month % 12 + 1
                day = min(data_obj.day, calendar.monthrange(year, month)[1])
                data_esp = date(year, month, day)
                nome_parcela = nome
                db.session.add(ContaReceber(nome=nome_parcela, valor=valor, data_esperada=data_esp,
                                            foto_path=foto_path, categoria=categoria))
            db.session.commit()
            flash(f'Recebível e seus {meses} meses recorrentes cadastrados com sucesso!', 'success')
        else:
            db.session.add(ContaReceber(nome=nome, valor=valor, data_esperada=data_obj,
                                        foto_path=foto_path, categoria=categoria))
            db.session.commit()
            flash('Recebível cadastrado com sucesso!', 'success')
        return redirect(url_for('receber'))

    pendentes = ContaReceber.query.filter_by(status='pendente').order_by(ContaReceber.data_esperada).all()
    recebidos = ContaReceber.query.filter_by(status='recebido').order_by(ContaReceber.data_esperada.desc()).limit(30).all()
    hoje = datetime.now().date()
    return render_template('receber.html', contas=pendentes, contas_recebidas=recebidos, hoje=hoje, today_date=hoje, today_str=hoje.strftime('%Y-%m-%d'))


@app.route('/receber/editar/<int:id>', methods=['POST'])
def editar_recebivel(id):
    recebivel = db.session.get(ContaReceber, id)
    if not recebivel:
        flash('Recebível não encontrado.', 'danger')
        return redirect(url_for('receber'))
    
    try:
        nome = request.form['nome']
        valor = float(request.form['valor'].replace(',', '.'))
        data_obj = datetime.strptime(request.form['data_esperada'], '%Y-%m-%d').date()
        categoria = request.form['categoria']

        if 'foto' in request.files:
            arquivo = request.files['foto']
            if arquivo.filename:
                # Remove anterior se houver
                if recebivel.foto_path:
                    antigo = os.path.join(app.config['UPLOAD_FOLDER'], recebivel.foto_path)
                    if os.path.exists(antigo):
                        try:
                            os.remove(antigo)
                        except Exception:
                            pass
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_rec_{arquivo.filename}")
                arquivo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                recebivel.foto_path = filename

        if request.form.get('remover_foto') == 'true':
            if recebivel.foto_path:
                antigo = os.path.join(app.config['UPLOAD_FOLDER'], recebivel.foto_path)
                if os.path.exists(antigo):
                    try:
                        os.remove(antigo)
                    except Exception:
                        pass
                recebivel.foto_path = None

        recebivel.nome = nome
        recebivel.valor = valor
        recebivel.data_esperada = data_obj
        recebivel.categoria = categoria

        db.session.commit()
        flash('Recebível atualizado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao atualizar recebível: {e}', 'danger')
        
    return redirect(url_for('receber'))


@app.route('/receber/deletar/<int:id>', methods=['POST', 'GET'])
def deletar_recebivel(id):
    recebivel = db.session.get(ContaReceber, id)
    if recebivel:
        if recebivel.foto_path:
            caminho = os.path.join(app.config['UPLOAD_FOLDER'], recebivel.foto_path)
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except Exception:
                    pass
        db.session.delete(recebivel)
        db.session.commit()
        flash('Recebível excluído com sucesso!', 'success')
    else:
        flash('Recebível não encontrado.', 'danger')
    return redirect(url_for('receber'))


@app.route('/receber/dar_baixa/<int:id>')
def dar_baixa_recebivel(id):
    recebivel = db.session.get(ContaReceber, id)
    if recebivel:
        recebivel.status = 'recebido'
        # Cria uma entrada correspondente de 'credito' em Financas
        novo_credito = Financas(
            valor=recebivel.valor,
            descricao=f"Recebimento: {recebivel.nome}",
            foto_path=recebivel.foto_path,
            tipo='credito'
        )
        db.session.add(novo_credito)
        db.session.flush()
        db.session.add(ItemGasto(
            financa_id=novo_credito.id,
            nome=recebivel.nome,
            quantidade=1.0,
            valor_unitario=recebivel.valor,
            valor_total=recebivel.valor,
            categoria=recebivel.categoria
        ))
        db.session.commit()
        flash(f'Recebível "{recebivel.nome}" recebido com sucesso!', 'success')
    return redirect(url_for('receber'))




@app.route('/orcamento', methods=['GET', 'POST'])
def orcamento():
    if request.method == 'POST':
        categoria = request.form['categoria']
        limite = float(request.form['limite'].replace(',', '.'))
        meta_raw = request.form.get('meta_economia', '').strip()
        meta = float(meta_raw.replace(',', '.')) if meta_raw else None
        existente = Orcamento.query.filter_by(categoria=categoria).first()
        if existente:
            existente.limite_mensal = limite
            existente.meta_economia = meta
        else:
            db.session.add(Orcamento(categoria=categoria, limite_mensal=limite, meta_economia=meta))
        db.session.commit()
        flash('Orçamento atualizado.', 'success')
        return redirect(url_for('orcamento'))

    hoje = date.today()
    primeiro_dia = date(hoje.year, hoje.month, 1)

    gastos_mes = defaultdict(float)
    for item in ItemGasto.query.join(Financas).filter(Financas.data >= primeiro_dia).all():
        gastos_mes[item.categoria or 'Outros'] += item.valor_total

    from theoos import insights

    orcamentos = Orcamento.query.all()
    savings = {}
    for o in orcamentos:
        gasto = gastos_mes.get(o.categoria, 0)
        prog = insights.budget_savings_progress(
            gasto, o.limite_mensal, getattr(o, "meta_economia", None)
        )
        if prog:
            savings[o.categoria] = prog
    return render_template(
        "orcamento.html",
        orcamentos=orcamentos,
        gastos_mes=dict(gastos_mes),
        savings=savings,
    )


# ── LISTA DE COMPRAS — ADICIONAR / DELETAR / LIMPAR ──────────────────────────

@app.route('/lista/add', methods=['POST'])
def lista_add():
    item = request.form.get('item', '').strip()
    if not item:
        return redirect(url_for('lista_compras'))
    try:
        quantidade = float(request.form.get('quantidade', '1').replace(',', '.'))
    except ValueError:
        quantidade = 1.0
    unidade   = request.form.get('unidade', 'un').strip() or 'un'
    categoria = request.form.get('categoria', 'Outros')
    marca     = request.form.get('marca', '').strip() or None
    db.session.add(ListaCompras(item=item, quantidade=quantidade,
                                unidade=unidade, categoria=categoria,
                                marca=marca, status='pendente',
                                criado_por=_actor()))
    db.session.commit()
    flash(f'"{item}" adicionado à lista!', 'success')
    return redirect(url_for('lista_compras'))


@app.route('/lista/add_from_history')
def add_from_history():
    item = request.args.get('item', '').strip()
    marca = request.args.get('marca', '').strip() or None
    unidade = request.args.get('unidade', 'un').strip() or 'un'
    categoria = request.args.get('categoria', 'Supermercado').strip()
    
    if item:
        existente = ListaCompras.query.filter_by(item=item, marca=marca, status='pendente').first()
        if existente:
            existente.quantidade += 1.0
        else:
            db.session.add(ListaCompras(
                item=item,
                marca=marca,
                quantidade=1.0,
                unidade=unidade,
                categoria=categoria,
                status='pendente'
            ))
        db.session.commit()
        flash(f'"{item}" adicionado à lista!', 'success')
    return redirect(url_for('lista_compras'))


@app.route('/lista/delete/<int:id>')
def lista_delete(id):
    item = db.session.get(ListaCompras, id)
    if item:
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for('lista_compras'))


@app.route('/lista/limpar', methods=['POST'])
def lista_limpar():
    ListaCompras.query.filter_by(status='comprado').delete()
    db.session.commit()
    flash('Itens concluídos removidos.', 'success')
    return redirect(url_for('lista_compras'))


@app.route('/lista/editar/<int:id>', methods=['POST'])
def lista_editar(id):
    item_obj = db.session.get(ListaCompras, id)
    if item_obj:
        item = request.form.get('item', '').strip()
        if not item:
            flash('O nome do item não pode ser vazio.', 'danger')
            return redirect(url_for('lista_compras'))
        try:
            quantidade = float(request.form.get('quantidade', '1').replace(',', '.'))
        except ValueError:
            quantidade = 1.0
        unidade = request.form.get('unidade', 'un').strip() or 'un'
        categoria = request.form.get('categoria', 'Outros')
        marca = request.form.get('marca', '').strip() or None
        
        item_obj.item = item
        item_obj.quantidade = quantidade
        item_obj.unidade = unidade
        item_obj.categoria = categoria
        item_obj.marca = marca
        db.session.commit()
        flash(f'"{item}" atualizado com sucesso!', 'success')
    else:
        flash('Item não encontrado.', 'danger')
    return redirect(url_for('lista_compras'))


@app.route('/lista/enviar_telegram')
def lista_enviar_telegram():
    from theoos import telegram_lista

    itens_pendentes = ListaCompras.query.filter_by(status='pendente').order_by(ListaCompras.categoria, ListaCompras.item).all()
    if not itens_pendentes:
        flash('Nenhum item pendente na lista de compras.', 'warning')
        return redirect(url_for('lista_compras'))

    token = os.getenv('TELEGRAM_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        flash('Configurações do Telegram ausentes no servidor.', 'danger')
        return redirect(url_for('lista_compras'))

    total_estimado = telegram_lista.calc_total_estimado(itens_pendentes, ItemGasto, db)

    try:
        import telebot
        bot = telebot.TeleBot(token)
        telegram_lista.send_lista_message(bot, chat_id, itens_pendentes, total_estimado=total_estimado)
        flash('Lista de compras enviada com sucesso para o Telegram!', 'success')
    except Exception as e:
        flash(f'Erro ao enviar mensagem via robô: {e}', 'danger')

    return redirect(url_for('lista_compras'))


@app.route('/lista/baixar_txt')
def lista_baixar_txt():
    itens_pendentes = ListaCompras.query.filter_by(status='pendente').all()
    
    # Formata o arquivo TXT
    txt = f"LISTA DE COMPRAS FAMÍLIA\n"
    txt += f"Gerada em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}\n"
    txt += "="*40 + "\n\n"
    
    if not itens_pendentes:
        txt += "Nenhum item pendente na lista.\n"
    else:
        por_categoria = defaultdict(list)
        for it in itens_pendentes:
            por_categoria[it.categoria].append(it)
            
        for cat, items in por_categoria.items():
            txt += f"[{cat.upper()}]\n"
            for it in items:
                qty_val = it.quantidade
                if qty_val == int(qty_val):
                    qty_str = str(int(qty_val))
                else:
                    qty_str = f"{qty_val:.1f}".replace('.', ',')
                txt += f"[ ] {it.item} - {qty_str} {it.unidade}\n"
            txt += "\n"
            
    txt += "="*40 + "\n"
    txt += f"Total: {len(itens_pendentes)} itens pendentes.\n"
    
    response = make_response(txt)
    response.headers["Content-Disposition"] = f"attachment; filename=lista_de_compras_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


@app.route('/api/categorias', methods=['POST'])
def adicionar_categoria_api():
    dados = request.get_json() or {}
    nome = dados.get('nome', '').strip()
    if not nome:
        return jsonify({'sucesso': False, 'erro': 'Nome inválido.'}), 400
    
    # Verifica se já existe (case-insensitive)
    existente = Categoria.query.filter(db.func.lower(Categoria.nome) == db.func.lower(nome)).first()
    if existente:
        return jsonify({'sucesso': True, 'nome': existente.nome, 'novo': False})
        
    try:
        nova_cat = Categoria(nome=nome)
        db.session.add(nova_cat)
        db.session.commit()
        return jsonify({'sucesso': True, 'nome': nome, 'novo': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'erro': f'Erro ao salvar: {e}'}), 500


# ── BULK ACTIONS — CONTAS A PAGAR ─────────────────────────────────────────────

@app.route('/api/contas/bulk_actions', methods=['POST'])
def bulk_actions_contas():
    dados = request.get_json() or {}
    action = dados.get('action', '').strip()
    ids = dados.get('ids', [])
    categoria_nova = dados.get('categoria', 'Outros')

    if not ids or action not in ('delete', 'pay', 'category'):
        return jsonify({'sucesso': False, 'erro': 'Parâmetros inválidos.'}), 400

    try:
        contas_selecionadas = Conta.query.filter(Conta.id.in_(ids), Conta.status == 'pendente').all()

        if action == 'delete':
            for c in contas_selecionadas:
                if c.foto_path:
                    caminho = os.path.join(app.config['UPLOAD_FOLDER'], c.foto_path)
                    if os.path.exists(caminho):
                        try:
                            os.remove(caminho)
                        except Exception:
                            pass
                db.session.delete(c)
            db.session.commit()
            return jsonify({'sucesso': True, 'mensagem': f'{len(contas_selecionadas)} conta(s) excluída(s).'})

        elif action == 'pay':
            for c in contas_selecionadas:
                c.status = 'pago'
                novo_gasto = Financas(valor=c.valor, descricao=f"Conta Paga: {c.nome}", foto_path=c.foto_path, tipo='debito')
                db.session.add(novo_gasto)
                db.session.flush()
                db.session.add(ItemGasto(
                    financa_id=novo_gasto.id,
                    nome=c.nome,
                    quantidade=1.0,
                    valor_unitario=c.valor,
                    valor_total=c.valor,
                    categoria=c.categoria
                ))
            db.session.commit()
            return jsonify({'sucesso': True, 'mensagem': f'{len(contas_selecionadas)} conta(s) marcada(s) como paga(s).'})

        elif action == 'category':
            for c in contas_selecionadas:
                c.categoria = categoria_nova
            db.session.commit()
            return jsonify({'sucesso': True, 'mensagem': f'Categoria alterada para "{categoria_nova}" em {len(contas_selecionadas)} conta(s).'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'erro': f'Erro: {e}'}), 500


# ── GERENCIAMENTO DE CATEGORIAS ───────────────────────────────────────────────

@app.route('/categorias', methods=['GET', 'POST'])
def categorias():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('Nome da categoria não pode ser vazio.', 'danger')
            return redirect(url_for('categorias'))
        existente = Categoria.query.filter(db.func.lower(Categoria.nome) == db.func.lower(nome)).first()
        if existente:
            flash(f'A categoria "{nome}" já existe.', 'warning')
            return redirect(url_for('categorias'))
        try:
            db.session.add(Categoria(nome=nome))
            db.session.commit()
            flash(f'Categoria "{nome}" criada com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar categoria: {e}', 'danger')
        return redirect(url_for('categorias'))

    todas = Categoria.query.order_by(Categoria.nome).all()
    from theoos import produtos as produtos_svc
    produtos_svc.seed_catalog_from_history(db, Produto, ItemGasto)
    produtos = produtos_svc.list_produtos_com_stats(db, Produto, ItemGasto)
    return render_template('categorias.html', categorias=todas, produtos=produtos)


@app.route('/categorias/editar/<int:id>', methods=['POST'])
def editar_categoria(id):
    cat = db.session.get(Categoria, id)
    if not cat:
        flash('Categoria não encontrada.', 'danger')
        return redirect(url_for('categorias'))
    nome_antigo = cat.nome
    nome_novo = request.form.get('nome', '').strip()
    if not nome_novo:
        flash('Nome não pode ser vazio.', 'danger')
        return redirect(url_for('categorias'))
    if nome_antigo.lower() == 'outros':
        flash('A categoria "Outros" não pode ser renomeada.', 'danger')
        return redirect(url_for('categorias'))
    # Verifica duplicata
    dup = Categoria.query.filter(
        db.func.lower(Categoria.nome) == db.func.lower(nome_novo),
        Categoria.id != id
    ).first()
    if dup:
        flash(f'Já existe uma categoria com o nome "{nome_novo}".', 'warning')
        return redirect(url_for('categorias'))
    try:
        # Cascade update em todas as tabelas relacionadas
        cat.nome = nome_novo
        Conta.query.filter_by(categoria=nome_antigo).update({'categoria': nome_novo})
        ContaReceber.query.filter_by(categoria=nome_antigo).update({'categoria': nome_novo})
        ItemGasto.query.filter_by(categoria=nome_antigo).update({'categoria': nome_novo})
        ListaCompras.query.filter_by(categoria=nome_antigo).update({'categoria': nome_novo})
        Orcamento.query.filter_by(categoria=nome_antigo).update({'categoria': nome_novo})
        db.session.commit()
        flash(f'Categoria renomeada de "{nome_antigo}" para "{nome_novo}" e atualizada em todos os registros.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao renomear: {e}', 'danger')
    return redirect(url_for('categorias'))


@app.route('/categorias/deletar/<int:id>', methods=['POST'])
def deletar_categoria(id):
    cat = db.session.get(Categoria, id)
    if not cat:
        flash('Categoria não encontrada.', 'danger')
        return redirect(url_for('categorias'))
    if cat.nome.lower() == 'outros':
        flash('A categoria "Outros" é protegida e não pode ser excluída.', 'danger')
        return redirect(url_for('categorias'))
    nome = cat.nome
    try:
        # Cascata: mover todos os registros para "Outros"
        Conta.query.filter_by(categoria=nome).update({'categoria': 'Outros'})
        ContaReceber.query.filter_by(categoria=nome).update({'categoria': 'Outros'})
        ItemGasto.query.filter_by(categoria=nome).update({'categoria': 'Outros'})
        ListaCompras.query.filter_by(categoria=nome).update({'categoria': 'Outros'})
        Orcamento.query.filter_by(categoria=nome).delete()
        db.session.delete(cat)
        db.session.commit()
        flash(f'Categoria "{nome}" excluída. Todos os registros foram movidos para "Outros".', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {e}', 'danger')
    return redirect(url_for('categorias'))


@app.route('/categorias/produto/salvar/<int:id>', methods=['POST'])
def salvar_produto_catalogo(id):
    from theoos import produtos as produtos_svc
    try:
        produtos_svc.update_produto_catalog(
            db, Produto, ItemGasto, ListaCompras, id,
            nome=request.form.get('nome', ''),
            marca=request.form.get('marca', ''),
            unidade=request.form.get('unidade', 'un'),
            categoria=request.form.get('categoria', 'Outros'),
            aliases_raw=request.form.get('aliases', ''),
        )
        return jsonify({'sucesso': True})
    except ValueError as e:
        return jsonify({'sucesso': False, 'erro': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'erro': str(e)}), 500


@app.route('/categorias/produto/fusao', methods=['POST'])
def fusao_produtos():
    from theoos import produtos as produtos_svc
    data = request.get_json(silent=True) or {}
    target_id = data.get('target_id')
    source_ids = data.get('source_ids') or []
    if not target_id or len(source_ids) < 1:
        return jsonify({'sucesso': False, 'erro': 'Selecione ao menos 2 produtos.'}), 400
    try:
        produtos_svc.merge_produtos(
            db, Produto, ItemGasto, ListaCompras,
            int(target_id), [int(s) for s in source_ids],
        )
        return jsonify({'sucesso': True})
    except ValueError as e:
        return jsonify({'sucesso': False, 'erro': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'erro': str(e)}), 500


@app.route('/categorias/produto/deletar/<int:id>', methods=['POST'])
def deletar_produto_catalogo(id):
    from theoos import produtos as produtos_svc
    try:
        produtos_svc.delete_produto_catalog(db, Produto, ItemGasto, id)
        return jsonify({'sucesso': True})
    except ValueError as e:
        return jsonify({'sucesso': False, 'erro': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'erro': str(e)}), 500


def _produto_sugestao_dict(nome, marca, unidade, categoria, ultimo_preco):
    return {
        'nome': nome,
        'marca': marca or '',
        'unidade': unidade or 'un',
        'categoria': categoria or 'Outros',
        'ultimo_preco': ultimo_preco,
    }


@app.route('/api/sugerir_produto')
def sugerir_produto():
    nome = request.args.get('nome', '').strip()
    if not nome:
        return jsonify({'categoria': None, 'ultimo_preco': None})

    itens = _buscar_sugestoes_produto(nome, limit=1)
    if itens:
        return jsonify({
            'categoria': itens[0]['categoria'],
            'ultimo_preco': itens[0]['ultimo_preco'],
        })
    return jsonify({'categoria': None, 'ultimo_preco': None})


@app.route('/api/sugerir_produtos')
def sugerir_produtos():
    q = request.args.get('q', request.args.get('nome', '')).strip()
    if len(q) < 2:
        return jsonify({'itens': []})
    return jsonify({'itens': _buscar_sugestoes_produto(q, limit=8)})


def _buscar_sugestoes_produto(q, limit=8):
    """Busca produtos no catálogo, histórico de gastos e lista de compras."""
    seen = set()
    results = []

    catalogo = Produto.query.filter(
        db.or_(
            Produto.nome.ilike(f'%{q}%'),
            Produto.aliases.ilike(f'%{q}%'),
        )
    ).order_by(Produto.nome).limit(limit * 2).all()

    for p in catalogo:
        key = (p.nome.lower(), (p.marca or '').strip().lower())
        if key in seen:
            continue
        seen.add(key)
        ultimo = (
            ItemGasto.query.filter_by(produto_id=p.id)
            .order_by(ItemGasto.id.desc())
            .first()
        )
        preco = ultimo.valor_unitario if ultimo else None
        results.append(_produto_sugestao_dict(
            p.nome, p.marca, p.unidade, p.categoria, preco
        ))
        if len(results) >= limit:
            return results

    gastos = ItemGasto.query.filter(
        db.or_(
            ItemGasto.nome.ilike(f'%{q}%'),
            ItemGasto.nome_normalizado.ilike(f'%{q}%'),
        )
    ).order_by(ItemGasto.id.desc()).limit(50).all()

    for g in gastos:
        nome = (g.nome_normalizado or g.nome or '').strip()
        if not nome:
            continue
        key = (nome.lower(), (g.marca or '').strip().lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(_produto_sugestao_dict(
            nome, g.marca, g.unidade, g.categoria, g.valor_unitario
        ))
        if len(results) >= limit:
            return results

    lista_itens = ListaCompras.query.filter(
        ListaCompras.item.ilike(f'%{q}%')
    ).order_by(ListaCompras.id.desc()).limit(30).all()

    for lc in lista_itens:
        nome = (lc.item or '').strip()
        if not nome:
            continue
        key = (nome.lower(), (lc.marca or '').strip().lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(_produto_sugestao_dict(
            nome, lc.marca, lc.unidade, lc.categoria, None
        ))
        if len(results) >= limit:
            break

    return results


# ── UPLOAD DE CUPOM PELO SITE (OCR via Gemini) ────────────────────────────────

@app.route('/upload_nota', methods=['GET', 'POST'])
def upload_nota():
    # Obter lista de cupons recentes (que possuem itens de gasto)
    try:
        recentes = Financas.query.filter(
            Financas.tipo == 'debito'
        ).join(ItemGasto).group_by(Financas.id).order_by(Financas.data.desc()).limit(15).all()
    except Exception as e:
        print(f"Erro ao buscar cupons recentes: {e}")
        recentes = []

    selected_cupom = None
    cupom_id = request.args.get('cupom_id', type=int)
    if cupom_id:
        selected_cupom = db.session.get(Financas, cupom_id)

    if request.method == 'GET':
        return render_template('upload_nota.html', recentes=recentes, selected_cupom=selected_cupom)

    arquivo = request.files.get('nota')
    if not arquivo or not arquivo.filename:
        flash('Selecione um arquivo de imagem.', 'danger')
        return redirect(url_for('upload_nota'))

    img_bytes = arquivo.read()

    # Deduplicação MD5
    foto_hash = hashlib.md5(img_bytes).hexdigest()
    try:
        if Financas.query.filter_by(foto_hash=foto_hash).first():
            flash('Este cupom já foi registrado anteriormente.', 'warning')
            return redirect(url_for('upload_nota'))
    except Exception:
        foto_hash = None

    # Lista pendente para cruzamento
    pendentes = ListaCompras.query.filter_by(status='pendente').all()
    lista_str = ", ".join(f"[ID:{p.id} {p.item}]" for p in pendentes) or "Lista vazia."

    from theoos import produtos as produtos_svc
    catalog = produtos_svc.build_catalog(db, ItemGasto, Produto)
    catalog_block = produtos_svc.catalog_prompt_block(catalog)

    # Detecta as categorias dinâmicas do banco
    try:
        cats_db = Categoria.query.all()
        categorias_prompt = ", ".join(f"'{c.nome}'" for c in cats_db)
    except Exception:
        categorias_prompt = "'Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros'"

    # Detecta MIME type pela extensão
    ext = arquivo.filename.rsplit('.', 1)[-1].lower()
    mime = 'image/png' if ext == 'png' else 'image/jpeg'
    image_part = genai_types.Part.from_bytes(data=img_bytes, mime_type=mime)

    prompt = f"""
Analise o cupom fiscal e extraia todos os itens comprados.
Cruze com a lista de compras pendentes: {lista_str}
Se um item da lista foi comprado (mesmo com nome diferente), inclua o ID em ids_comprados.

Classifique cada item em UMA categoria do sistema: [{categorias_prompt}]. Escolha a que melhor se adapta.

Para cada item, além de extrair o nome original/bruto impresso no cupom (no campo "nome"), determine e inclua:
1. Um nome simplificado, limpo e padronizado em "nome_normalizado" (ex: se "LEITE UHT INT LIDER 1L", o nome_normalizado será "Leite Integral"; se "LJA PERA", será "Laranja Pera"; se "ARROZ T1 PRATO FINO 5KG", será "Arroz Branco").
2. A marca do produto no campo "marca" (ex: "Lider", "Prato Fino", "Nestlé"). Se não houver marca identificável, retorne null.
3. A unidade de medida do produto no campo "unidade" (use uma destas siglas: "un", "kg", "g", "l", "ml", "Cx"). Se não for evidente, use "un".
{catalog_block.strip()}
Retorne SOMENTE JSON puro:
{{"mercado":"Nome","data":"DD/MM/AAAA","total_nota":0.00,"itens":[{{"nome":"NOME ORIGINAL","nome_normalizado":"Nome Limpo","marca":"Marca ou null","quantidade":1.0,"valor_unitario":0.00,"valor_total":0.00,"categoria":"Supermercado","unidade":"un"}}],"ids_comprados":[]}}
"""
    try:
        resposta = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, image_part]
        )
        texto = resposta.text.strip()
        if texto.startswith('```'):
            texto = texto.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
        dados = json.loads(texto)
    except Exception as e:
        flash(f'Erro ao processar imagem com IA: {e}', 'danger')
        return redirect(url_for('upload_nota'))

    mercado     = dados.get('mercado', 'Desconhecido')
    total       = float(dados.get('total_nota', 0.0))
    itens_lista = dados.get('itens', [])
    ids_riscados = dados.get('ids_comprados', [])

    produtos_svc.normalize_itens_ocr(db, ItemGasto, itens_lista, Produto)

    # Salva a foto fisicamente no disco e registra o caminho
    filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_cupom_{foto_hash[:8]}.{ext}")
    try:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(filepath, 'wb') as f:
            f.write(img_bytes)
        foto_path = filename
    except Exception as e:
        print(f"Erro ao salvar arquivo de cupom: {e}")
        foto_path = None

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

    novo_gasto = Financas(
        valor=total,
        descricao=f"IA: {mercado}",
        foto_hash=foto_hash,
        foto_path=foto_path,
        data=data_gasto,
        criado_por=_actor(),
    )
    db.session.add(novo_gasto)
    db.session.flush()

    for item in itens_lista:
        cat = item.get('categoria', 'Outros')
        db.session.add(ItemGasto(
            financa_id=novo_gasto.id,
            produto_id=item.get('produto_id'),
            nome=item.get('nome', 'Desconhecido'),
            nome_normalizado=item.get('nome_normalizado'),
            marca=item.get('marca'),
            quantidade=float(item.get('quantidade', 1.0)),
            valor_unitario=float(item.get('valor_unitario', 0.0)),
            valor_total=float(item.get('valor_total', 0.0)),
            categoria=cat,
            unidade=item.get('unidade', 'un'),
            mercado=mercado[:80] if mercado else None,
        ))


    for cid in ids_riscados:
        lc = db.session.get(ListaCompras, int(cid))
        if lc and lc.status == 'pendente':
            lc.status = 'comprado'
            lc.marcado = False

    db.session.commit()

    flash(f'Cupom de {mercado} processado! {len(itens_lista)} itens • R$ {total:.2f}', 'success')
    return redirect(url_for('upload_nota', cupom_id=novo_gasto.id))


@app.route('/upload_nota/editar/<int:cupom_id>', methods=['POST'])
def editar_cupom_header(cupom_id):
    cupom = db.session.get(Financas, cupom_id)
    if not cupom:
        flash('Cupom não encontrado.', 'danger')
        return redirect(url_for('upload_nota'))
    
    descricao = request.form.get('descricao', '').strip()
    data_str = request.form.get('data', '').strip()
    
    if not descricao:
        flash('A descrição do cupom não pode ser vazia.', 'danger')
        return redirect(url_for('upload_nota', cupom_id=cupom_id))
        
    try:
        cupom.descricao = descricao
        if data_str:
            cupom.data = datetime.strptime(data_str, '%Y-%m-%d')
        db.session.commit()
        flash('Cupom atualizado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar cupom: {e}', 'danger')
        
    return redirect(url_for('upload_nota', cupom_id=cupom_id))


@app.route('/upload_nota/deletar/<int:cupom_id>', methods=['POST', 'GET'])
def deletar_cupom(cupom_id):
    cupom = db.session.get(Financas, cupom_id)
    if cupom:
        if cupom.foto_path:
            caminho = os.path.join(app.config['UPLOAD_FOLDER'], cupom.foto_path)
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except Exception:
                    pass
        # Remove os itens
        ItemGasto.query.filter_by(financa_id=cupom_id).delete()
        db.session.delete(cupom)
        db.session.commit()
        flash('Cupom e itens excluídos com sucesso!', 'success')
    else:
        flash('Cupom não encontrado.', 'danger')
    return redirect(url_for('upload_nota'))


@app.route('/upload_nota/item/editar/<int:item_id>', methods=['POST'])
def editar_item_cupom(item_id):
    item = db.session.get(ItemGasto, item_id)
    if not item:
        return jsonify({'sucesso': False, 'erro': 'Item não encontrado.'}), 404
        
    nome = request.form.get('nome', '').strip()
    nome_normalizado = request.form.get('nome_normalizado', '').strip()
    marca = request.form.get('marca', '').strip()
    categoria = request.form.get('categoria', '').strip()
    unidade = request.form.get('unidade', '').strip()
    quantidade_str = request.form.get('quantidade', '').strip()
    
    if not nome:
        return jsonify({'sucesso': False, 'erro': 'O nome do produto não pode ser vazio.'}), 400
        
    try:
        item.nome = nome
        item.nome_normalizado = nome_normalizado if nome_normalizado else None
        item.marca = marca if marca else None
        if categoria:
            item.categoria = categoria
        if unidade:
            item.unidade = unidade
        if quantidade_str:
            try:
                item.quantidade = float(quantidade_str.replace(',', '.'))
                item.valor_total = item.valor_unitario * item.quantidade
            except ValueError:
                pass
                
        db.session.commit()
        
        # Atualiza o valor total do cupom (Financas)
        cupom = item.nota
        if cupom:
            total_cupom = db.session.query(db.func.sum(ItemGasto.valor_total)).filter(ItemGasto.financa_id == cupom.id).scalar() or 0.0
            cupom.valor = total_cupom
            db.session.commit()
            
        return jsonify({
            'sucesso': True,
            'mensagem': 'Item atualizado com sucesso!',
            'nome': item.nome,
            'nome_normalizado': item.nome_normalizado,
            'marca': item.marca,
            'categoria': item.categoria,
            'unidade': item.unidade,
            'quantidade': item.quantidade
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'erro': f'Erro: {e}'}), 500


@app.route('/upload_nota/salvar_tudo/<int:cupom_id>', methods=['POST'])
def salvar_tudo_cupom(cupom_id):
    cupom = db.session.get(Financas, cupom_id)
    if not cupom:
        return jsonify({'sucesso': False, 'erro': 'Cupom não encontrado.'}), 404
    
    dados = request.get_json()
    if not dados:
        return jsonify({'sucesso': False, 'erro': 'Dados inválidos.'}), 400
        
    descricao = dados.get('descricao', '').strip()
    data_str = dados.get('data', '').strip()
    itens_dados = dados.get('items', [])
    
    if not descricao:
        return jsonify({'sucesso': False, 'erro': 'A descrição do cupom não pode ser vazia.'}), 400
        
    try:
        # Atualiza cabeçalho
        cupom.descricao = descricao
        if data_str:
            cupom.data = datetime.strptime(data_str, '%Y-%m-%d')
            
        # Atualiza itens
        for item_dado in itens_dados:
            item_id = item_dado.get('id')
            item = db.session.get(ItemGasto, item_id)
            if item and item.financa_id == cupom.id:
                nome = item_dado.get('nome', '').strip()
                nome_normalizado = item_dado.get('nome_normalizado', '').strip()
                marca = item_dado.get('marca', '').strip()
                categoria = item_dado.get('categoria', '').strip()
                unidade = item_dado.get('unidade', '').strip()
                quantidade = item_dado.get('quantidade')
                
                if nome:
                    item.nome = nome
                item.nome_normalizado = nome_normalizado if nome_normalizado else None
                item.marca = marca if marca else None
                if categoria:
                    item.categoria = categoria
                if unidade:
                    item.unidade = unidade
                if quantidade is not None:
                    try:
                        item.quantidade = float(quantidade)
                        item.valor_total = item.valor_unitario * item.quantidade
                    except (ValueError, TypeError):
                        pass
                    
        db.session.commit()
        
        # Atualiza o valor total do cupom (Financas)
        total_cupom = db.session.query(db.func.sum(ItemGasto.valor_total)).filter(ItemGasto.financa_id == cupom.id).scalar() or 0.0
        cupom.valor = total_cupom
        db.session.commit()
        
        flash('Cupom e todos os seus itens foram atualizados com sucesso!', 'success')
        return jsonify({'sucesso': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'erro': f'Erro ao salvar tudo: {e}'}), 500



@app.route('/upload_nota/item/deletar/<int:item_id>', methods=['POST'])
def deletar_item_cupom(item_id):
    item = db.session.get(ItemGasto, item_id)
    if not item:
        return jsonify({'sucesso': False, 'erro': 'Item não encontrado.'}), 404
        
    cupom = item.nota
    valor_total_item = item.valor_total
    
    try:
        db.session.delete(item)
        
        # Atualiza o valor total do cupom (Financas)
        outros_itens_count = ItemGasto.query.filter_by(financa_id=cupom.id).count()
        if outros_itens_count == 0:
            if cupom.foto_path:
                caminho = os.path.join(app.config['UPLOAD_FOLDER'], cupom.foto_path)
                if os.path.exists(caminho):
                    try:
                        os.remove(caminho)
                    except Exception:
                        pass
            db.session.delete(cupom)
            db.session.commit()
            flash('Cupom removido por não conter mais itens.', 'info')
            return jsonify({'sucesso': True, 'reload': True, 'mensagem': 'Cupom removido por não conter mais itens.'})
        else:
            cupom.valor = max(0.0, cupom.valor - valor_total_item)
            db.session.commit()
            return jsonify({
                'sucesso': True,
                'reload': False,
                'mensagem': 'Item excluído com sucesso!'
            })
    except Exception as e:
        db.session.rollback()
        return jsonify({'sucesso': False, 'erro': f'Erro: {e}'}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    as_service = os.getenv('THEOOS_SERVICE', '').strip() in ('1', 'true', 'yes')
    debug = os.getenv('FLASK_DEBUG', '').lower() in ('1', 'true') and not as_service
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        use_reloader=debug,
    )
