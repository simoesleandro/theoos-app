"""Blueprint do dashboard, pesquisa de preços e favicon."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, make_response, render_template, request
from sqlalchemy import desc, func

from models import Conta, ContaReceber, Financas, ItemGasto, ListaCompras, Orcamento, db
from theoos import insights

bp = Blueprint("dashboard", __name__)


def _sparkline_data(db, Financas, ItemGasto, meses=6, top_n=5):
    raw = insights.monthly_spending_by_category(db, Financas, ItemGasto, meses=meses, top_n=top_n)
    out = []
    for t in raw:
        serie = t["serie"]
        if not serie:
            continue
        maxv = max((s["valor"] for s in serie), default=1.0) or 1.0
        n = len(serie)
        pts = []
        for i, s in enumerate(serie):
            x = i * (120 / (n - 1)) if n > 1 else 60.0
            y = 38 - (s["valor"] / maxv * 36) if maxv > 0 else 38
            pts.append(f"{x:.1f},{y:.1f}")
        out.append({**t, "polyline": " ".join(pts)})
    return out


@bp.route("/")
def index():
    hoje = date.today()
    primeiro_dia = date(hoje.year, hoje.month, 1)
    hoje_dt = datetime.combine(hoje, datetime.min.time())
    primeiro_dia_dt = datetime.combine(primeiro_dia, datetime.min.time())

    total_debitos_mes = (
        db.session.query(db.func.sum(Financas.valor))
        .filter(Financas.data >= primeiro_dia_dt, Financas.tipo == "debito")
        .scalar()
        or 0.0
    )
    total_creditos_mes = (
        db.session.query(db.func.sum(Financas.valor))
        .filter(Financas.data >= primeiro_dia_dt, Financas.tipo == "credito")
        .scalar()
        or 0.0
    )
    saldo_mes = total_creditos_mes - total_debitos_mes

    if hoje.month == 1:
        primeiro_dia_anterior = date(hoje.year - 1, 12, 1)
        ultimo_dia_anterior = date(hoje.year - 1, 12, 31)
    else:
        primeiro_dia_anterior = date(hoje.year, hoje.month - 1, 1)
        ultimo_dia_anterior = primeiro_dia - timedelta(days=1)

    dt_inicio_anterior = datetime.combine(primeiro_dia_anterior, datetime.min.time())
    dt_fim_anterior = datetime.combine(ultimo_dia_anterior, datetime.max.time())

    total_debitos_mes_anterior = (
        db.session.query(db.func.sum(Financas.valor))
        .filter(
            Financas.tipo == "debito",
            Financas.data >= dt_inicio_anterior,
            Financas.data <= dt_fim_anterior,
        )
        .scalar()
        or 0.0
    )
    total_creditos_mes_anterior = (
        db.session.query(db.func.sum(Financas.valor))
        .filter(
            Financas.tipo == "credito",
            Financas.data >= dt_inicio_anterior,
            Financas.data <= dt_fim_anterior,
        )
        .scalar()
        or 0.0
    )

    projecoes: dict[int, dict[str, float]] = {}
    for dias in (7, 15, 30, 365):
        dt_limite = hoje + timedelta(days=dias)
        receitas_periodo = (
            db.session.query(db.func.sum(ContaReceber.valor))
            .filter(ContaReceber.status == "pendente", ContaReceber.data_esperada <= dt_limite)
            .scalar()
            or 0.0
        )
        despesas_periodo = (
            db.session.query(db.func.sum(Conta.valor))
            .filter(Conta.status == "pendente", Conta.data_vencimento <= dt_limite)
            .scalar()
            or 0.0
        )
        projecoes[dias] = {
            "receitas": receitas_periodo,
            "despesas": despesas_periodo,
            "saldo_periodo": receitas_periodo - despesas_periodo,
            "saldo_projetado": saldo_mes + (receitas_periodo - despesas_periodo),
        }

    pendentes = ListaCompras.query.filter_by(status="pendente").count()
    lista_preview = ListaCompras.query.filter_by(status="pendente").limit(5).all()
    contas_pendentes_count = Conta.query.filter_by(status="pendente").count()
    num_transacoes = Financas.query.filter(Financas.data >= primeiro_dia_dt).count()
    notas = Financas.query.order_by(Financas.data.desc()).limit(5).all()

    datas_grafico: list[str] = []
    debitos_agrupados: dict[str, float] = defaultdict(float)
    creditos_agrupados: dict[str, float] = defaultdict(float)
    for i in range(29, -1, -1):
        dia_str = (hoje - timedelta(days=i)).strftime("%d/%m")
        datas_grafico.append(dia_str)
        debitos_agrupados[dia_str] = 0.0
        creditos_agrupados[dia_str] = 0.0

    for nota in Financas.query.filter(
        Financas.data >= datetime.combine(hoje - timedelta(days=29), datetime.min.time())
    ).all():
        dia_str = nota.data.strftime("%d/%m")
        if dia_str in debitos_agrupados:
            if nota.tipo == "credito":
                creditos_agrupados[dia_str] += nota.valor
            else:
                debitos_agrupados[dia_str] += nota.valor

    valores_debitos = [debitos_agrupados[d] for d in datas_grafico]
    valores_creditos = [creditos_agrupados[d] for d in datas_grafico]

    gastos_por_cat: dict[str, float] = defaultdict(float)
    for item in ItemGasto.query.join(Financas).filter(
        Financas.data >= primeiro_dia_dt, Financas.tipo == "debito"
    ).all():
        gastos_por_cat[item.categoria or "Outros"] += item.valor_total

    semana = insights.week_agenda(db, Conta, ContaReceber, hoje, days=7)
    orcamento_status = insights.budget_status(db, Orcamento, ItemGasto, Financas)
    alertas_preco = insights.price_spike_alerts(db, ItemGasto, Financas)[:5]
    habitos_sumidos = insights.missing_habit_products(db, ItemGasto, Financas)[:4]
    try:
        tendencias_cat = _sparkline_data(db, Financas, ItemGasto, meses=6, top_n=5)
    except Exception:
        tendencias_cat = []

    return render_template(
        "index.html",
        total=total_debitos_mes,
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
        today_str=hoje.strftime("%Y-%m-%d"),
        semana=semana,
        orcamento_status=orcamento_status,
        alertas_preco=alertas_preco,
        habitos_sumidos=habitos_sumidos,
        tendencias_cat=tendencias_cat,
    )


@bp.route("/pesquisa")
def pesquisa():
    termo = request.args.get("q", "").strip()

    resultados = (
        insights.pesquisa_resultados(db, ItemGasto, Financas, termo) if termo else []
    )
    minmax_unidades = insights.minmax_por_unidade(resultados) if resultados else {}

    itens_populares: list[str] = []
    try:
        popular_items_query = (
            db.session.query(
                func.coalesce(ItemGasto.nome_normalizado, ItemGasto.nome).label("nome_item"),
                func.sum(ItemGasto.valor_total).label("total_gasto"),
            )
            .group_by(func.coalesce(ItemGasto.nome_normalizado, ItemGasto.nome))
            .order_by(desc("total_gasto"))
            .limit(12)
            .all()
        )
        itens_populares = [
            item.nome_item for item in popular_items_query if item.nome_item and len(item.nome_item) <= 25
        ]
    except Exception:
        pass

    for default_item in ("Leite", "Arroz", "Feijão", "Pão de Forma", "Frango", "Detergente", "Café", "Açúcar"):
        if len(itens_populares) >= 8:
            break
        if not any(default_item.lower() == item.lower() for item in itens_populares):
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


@bp.route("/favicon.ico")
def favicon():
    return current_app.send_static_file("icons/favicon.svg")

