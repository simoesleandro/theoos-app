"""Blueprint de relatórios e exports."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import StringIO

import csv
from flask import Blueprint, flash, make_response, redirect, render_template, request, url_for

from models import Financas, ItemGasto, db
from theoos import insights

bp = Blueprint("relatorios", __name__)


@bp.route("/relatorios")
def relatorios():
    page = request.args.get("page", 1, type=int)
    paginacao = Financas.query.order_by(Financas.data.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    total_geral_debitos = (
        db.session.query(db.func.sum(Financas.valor))
        .filter(Financas.tipo == "debito")
        .scalar()
        or 0.0
    )
    total_geral_creditos = (
        db.session.query(db.func.sum(Financas.valor))
        .filter(Financas.tipo == "credito")
        .scalar()
        or 0.0
    )
    saldo_geral = total_geral_creditos - total_geral_debitos

    gastos_agrupados: dict[str, float] = defaultdict(float)
    for nota in Financas.query.filter_by(tipo="debito").all():
        gastos_agrupados[nota.data.strftime("%d/%m")] += nota.valor

    gastos_por_cat: dict[str, float] = defaultdict(float)
    for item in ItemGasto.query.join(Financas).filter(Financas.tipo == "debito").all():
        gastos_por_cat[item.categoria or "Outros"] += item.valor_total

    total_debitos_count = Financas.query.filter_by(tipo="debito").count()
    media_gasto = total_geral_debitos / total_debitos_count if total_debitos_count > 0 else 0.0
    maior_compra = (
        db.session.query(db.func.max(Financas.valor))
        .filter(Financas.tipo == "debito")
        .scalar()
        or 0.0
    )

    categoria_lider = "Nenhuma"
    if gastos_por_cat:
        categoria_lider = max(gastos_por_cat, key=gastos_por_cat.get)

    variacoes_principais = insights.price_variations(db, ItemGasto, Financas, limit=5)

    from models import Conta, ContaReceber

    hoje_data = date.today()

    contas_vencidas_q = Conta.query.filter(
        Conta.status == "pendente", Conta.data_vencimento < hoje_data
    ).all()
    total_vencidas_valor = sum(c.valor for c in contas_vencidas_q)
    total_vencidas_qtd = len(contas_vencidas_q)

    contas_a_vencer_q = Conta.query.filter(
        Conta.status == "pendente", Conta.data_vencimento >= hoje_data
    ).all()
    total_a_vencer_valor = sum(c.valor for c in contas_a_vencer_q)
    total_a_vencer_qtd = len(contas_a_vencer_q)

    periodo_inicio_str = request.args.get("periodo_inicio", "")
    periodo_fim_str = request.args.get("periodo_fim", "")

    try:
        periodo_inicio = (
            datetime.strptime(periodo_inicio_str, "%Y-%m-%d").date()
            if periodo_inicio_str
            else hoje_data
        )
    except ValueError:
        periodo_inicio = hoje_data
    try:
        periodo_fim = (
            datetime.strptime(periodo_fim_str, "%Y-%m-%d").date()
            if periodo_fim_str
            else hoje_data + timedelta(days=60)
        )
    except ValueError:
        periodo_fim = hoje_data + timedelta(days=60)

    contas_periodo = (
        Conta.query.filter(
            Conta.status == "pendente",
            Conta.data_vencimento >= periodo_inicio,
            Conta.data_vencimento <= periodo_fim,
        )
        .order_by(Conta.data_vencimento)
        .all()
    )
    soma_pagar_periodo = sum(c.valor for c in contas_periodo)

    receber_periodo = (
        ContaReceber.query.filter(
            ContaReceber.status == "pendente",
            ContaReceber.data_esperada >= periodo_inicio,
            ContaReceber.data_esperada <= periodo_fim,
        )
        .order_by(ContaReceber.data_esperada)
        .all()
    )
    soma_receber_periodo = sum(r.valor for r in receber_periodo)

    saldo_projetado_periodo = soma_receber_periodo - soma_pagar_periodo

    previsao_categoria_dict: dict[str, float] = defaultdict(float)
    for c in contas_periodo:
        previsao_categoria_dict[c.categoria] += c.valor

    previsao_categoria = sorted(
        [{"categoria": cat, "valor": val} for cat, val in previsao_categoria_dict.items()],
        key=lambda x: x["valor"],
        reverse=True,
    )

    comp_inicio_str = request.args.get("comp_inicio", "")
    comp_fim_str = request.args.get("comp_fim", "")
    primeiro_dia_mes = date(hoje_data.year, hoje_data.month, 1)

    try:
        comp_inicio = (
            datetime.strptime(comp_inicio_str, "%Y-%m-%d").date()
            if comp_inicio_str
            else primeiro_dia_mes
        )
    except ValueError:
        comp_inicio = primeiro_dia_mes

    try:
        comp_fim = (
            datetime.strptime(comp_fim_str, "%Y-%m-%d").date()
            if comp_fim_str
            else hoje_data
        )
    except ValueError:
        comp_fim = hoje_data

    def shift_month(dt, months):
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
        total = (
            db.session.query(db.func.sum(Financas.valor))
            .filter(
                Financas.tipo == "debito",
                Financas.data >= start_dt,
                Financas.data <= end_dt,
            )
            .scalar()
            or 0.0
        )
        results = (
            db.session.query(
                ItemGasto.categoria,
                db.func.sum(ItemGasto.valor_total),
            )
            .join(Financas)
            .filter(
                Financas.tipo == "debito",
                Financas.data >= start_dt,
                Financas.data <= end_dt,
            )
            .group_by(ItemGasto.categoria)
            .all()
        )
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
        comparativo_categorias.append(
            {
                "categoria": cat,
                "valor_prev": val_prev,
                "valor_atual": val_atual,
                "valor_next": val_next,
                "diff_prev_pct": diff_prev_pct,
            }
        )
    comparativo_categorias.sort(key=lambda x: x["valor_atual"], reverse=True)

    return render_template(
        "relatorios.html",
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
        hoje=hoje_data,
    )


@bp.route("/relatorios/deletar/<int:id>", methods=["POST"])
def deletar_transacao(id: int):
    nota = db.session.get(Financas, id)
    if nota:
        if nota.foto_path:
            from flask import current_app
            import os

            caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], nota.foto_path)
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except Exception:
                    pass

        ItemGasto.query.filter_by(financa_id=id).delete()
        from theoos import audit

        audit.log_action(db, "delete", "Financas", id, nota.descricao, _actor())
        db.session.delete(nota)
        db.session.commit()
        flash("Transação excluída com sucesso!", "success")
    else:
        flash("Transação não encontrada.", "danger")
    return redirect(url_for("relatorios.relatorios"))


def _actor() -> str:
    from flask import session

    return session.get("theoos_actor") or "web"


@bp.route("/exportar")
def exportar():
    itens = ItemGasto.query.all()
    si = StringIO()
    cw = csv.writer(si, delimiter=";")
    cw.writerow(["Data", "Mercado", "Produto", "Qtd", "Valor Unitário", "Valor Total", "Categoria"])
    for i in itens:
        cw.writerow(
            [
                i.nota.data.strftime("%d/%m/%Y"),
                i.nota.descricao.replace("IA: ", ""),
                i.nome,
                i.quantidade,
                f"{i.valor_unitario:.2f}".replace(".", ","),
                f"{i.valor_total:.2f}".replace(".", ","),
                i.categoria,
            ]
        )
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=relatorio_theoos.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8-sig"
    return output


@bp.route("/exportar/pdf")
def exportar_pdf():
    from theoos import pdf_report

    hoje = date.today()
    mes_param = request.args.get("mes", "")
    if mes_param and len(mes_param) == 7:
        try:
            y, m = mes_param.split("-")
            year, month = int(y), int(m)
        except ValueError:
            year, month = hoje.year, hoje.month
    else:
        year, month = hoje.year, hoje.month

    primeiro, ultimo = pdf_report.month_bounds(year, month)
    debitos = (
        db.session.query(db.func.sum(Financas.valor))
        .filter(
            Financas.tipo == "debito",
            Financas.data >= primeiro,
            Financas.data <= ultimo,
        )
        .scalar()
        or 0.0
    )
    creditos = (
        db.session.query(db.func.sum(Financas.valor))
        .filter(
            Financas.tipo == "credito",
            Financas.data >= primeiro,
            Financas.data <= ultimo,
        )
        .scalar()
        or 0.0
    )
    transacoes = []
    for n in (
        Financas.query.filter(Financas.data >= primeiro, Financas.data <= ultimo)
        .order_by(Financas.data.desc())
        .all()
    ):
        transacoes.append(
            {
                "data": n.data.strftime("%d/%m/%Y"),
                "descricao": n.descricao,
                "valor": n.valor,
                "tipo": n.tipo or "debito",
            }
        )

    gastos_cat = []
    cat_map: dict[str, float] = {}
    for item in (
        ItemGasto.query.join(Financas)
        .filter(
            Financas.data >= primeiro,
            Financas.data <= ultimo,
            Financas.tipo == "debito",
        )
        .all()
    ):
        cat = item.categoria or "Outros"
        cat_map[cat] = cat_map.get(cat, 0.0) + item.valor_total
    gastos_cat = sorted(cat_map.items(), key=lambda x: -x[1])

    from models import Conta

    contas_pendentes = []
    for c in Conta.query.filter_by(status="pendente").order_by(Conta.data_vencimento).all():
        if c.data_vencimento.year == year and c.data_vencimento.month == month:
            contas_pendentes.append(
                {
                    "nome": c.nome,
                    "vencimento": c.data_vencimento.strftime("%d/%m/%Y"),
                    "valor": c.valor,
                }
            )

    pdf_bytes = pdf_report.build_monthly_pdf(
        year,
        month,
        debitos,
        creditos,
        transacoes,
        gastos_cat,
        contas_pendentes,
    )
    fname = f"theoos-{year}-{month:02d}.pdf"
    if isinstance(pdf_bytes, bytearray):
        pdf_bytes = bytes(pdf_bytes)
    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Length"] = str(len(pdf_bytes))
    resp.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp
