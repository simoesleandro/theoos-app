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
