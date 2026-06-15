"""Blueprint de orçamento."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models import Financas, ItemGasto, Orcamento, db
from theoos import insights

bp = Blueprint("orcamento", __name__)


@bp.route("/orcamento", methods=["GET", "POST"])
def orcamento():
    if request.method == "POST":
        categoria = request.form["categoria"]
        limite = float(request.form["limite"].replace(",", "."))
        meta_raw = request.form.get("meta_economia", "").strip()
        meta = float(meta_raw.replace(",", ".")) if meta_raw else None
        existente = Orcamento.query.filter_by(categoria=categoria).first()
        if existente:
            existente.limite_mensal = limite
            existente.meta_economia = meta
        else:
            db.session.add(
                Orcamento(categoria=categoria, limite_mensal=limite, meta_economia=meta)
            )
        db.session.commit()
        flash("Orçamento atualizado.", "success")
        return redirect(url_for("orcamento.orcamento"))

    hoje = date.today()
    primeiro_dia = date(hoje.year, hoje.month, 1)

    gastos_mes: dict[str, float] = defaultdict(float)
    for item in ItemGasto.query.join(Financas).filter(Financas.data >= primeiro_dia).all():
        gastos_mes[item.categoria or "Outros"] += item.valor_total

    orcamentos = Orcamento.query.all()
    savings: dict = {}
    envelopes: list[dict] = []
    for o in orcamentos:
        gasto = gastos_mes.get(o.categoria, 0)
        prog = insights.budget_savings_progress(
            gasto, o.limite_mensal, getattr(o, "meta_economia", None)
        )
        if prog:
            savings[o.categoria] = prog
        saldo_anterior = float(getattr(o, "saldo_mes_anterior", 0.0) or 0.0)
        disponivel = float(o.limite_mensal) + saldo_anterior
        restante = disponivel - gasto
        envelopes.append(
            {
                "categoria": o.categoria,
                "limite": float(o.limite_mensal),
                "saldo_anterior": saldo_anterior,
                "disponivel": disponivel,
                "gasto": gasto,
                "restante": restante,
                "excedeu": restante < 0,
                "pct": (gasto / disponivel * 100) if disponivel > 0 else 0,
            }
        )

    return render_template(
        "orcamento.html",
        orcamentos=orcamentos,
        gastos_mes=dict(gastos_mes),
        savings=savings,
        envelopes=envelopes,
    )


@bp.route("/orcamento/fechar", methods=["POST"])
def fechar_mes():
    """Fecha o mês atual: para cada orçamento, salva o saldo (limite - gasto)
    como saldo_mes_anterior para o próximo mês. Saldos negativos são zerados
    (não transportamos dívidas para o envelope seguinte)."""
    hoje = date.today()
    primeiro_dia = date(hoje.year, hoje.month, 1)

    gastos_mes: dict[str, float] = defaultdict(float)
    for item in ItemGasto.query.join(Financas).filter(Financas.data >= primeiro_dia).all():
        gastos_mes[item.categoria or "Outros"] += item.valor_total

    count = 0
    for o in Orcamento.query.all():
        gasto = gastos_mes.get(o.categoria, 0)
        saldo = float(o.limite_mensal) - gasto
        o.saldo_mes_anterior = max(saldo, 0.0)
        count += 1
    db.session.commit()
    flash(
        f"Mês fechado para {count} orçamento(s). Saldos restantes foram transportados.",
        "success",
    )
    return redirect(url_for("orcamento.orcamento"))
