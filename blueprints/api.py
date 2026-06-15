"""Blueprint de APIs internas (insights, vencimentos)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from models import Conta, ContaReceber, Financas, ItemGasto, ListaCompras, Orcamento, db
from theoos import insights
from theoos.db_migrate import get_setting
from theoos.extensions import limiter

bp = Blueprint("api", __name__)


@bp.route("/api/insights")
@limiter.limit("60 per minute")
def api_insights():
    return jsonify(
        {
            "cesta": insights.basket_estimates_by_store(db, ListaCompras, ItemGasto, Financas),
            "alertas_preco": insights.price_spike_alerts(db, ItemGasto, Financas),
            "habitos": insights.missing_habit_products(db, ItemGasto, Financas),
            "orcamento": insights.budget_status(db, Orcamento, ItemGasto, Financas),
        }
    )


@bp.route("/api/vencimentos")
@limiter.limit("30 per minute")
def api_vencimentos():
    from theoos.recurring import (
        contas_due_for_reminder,
        contas_overdue,
        parse_reminder_days,
        receber_due_for_reminder,
    )

    hoje = date.today()
    enabled = get_setting(db, "web_notify", "1") == "1"
    days_str = get_setting(db, "reminder_days", "0,1,2,7") or "0,1,2,7"
    contas_out = []
    receber_out = []
    seen_c = set()
    seen_r = set()

    for c in contas_overdue(db, Conta):
        seen_c.add(c.id)
        dias_atraso = (hoje - c.data_vencimento).days
        contas_out.append(
            {
                "id": c.id,
                "nome": c.nome,
                "valor": c.valor,
                "vencimento": c.data_vencimento.isoformat(),
                "dias": -dias_atraso,
                "quando": f"vencida há {dias_atraso} dia(s)",
            }
        )

    for dias in parse_reminder_days(days_str):
        for c in contas_due_for_reminder(db, Conta, dias):
            if c.id in seen_c:
                continue
            seen_c.add(c.id)
            contas_out.append(
                {
                    "id": c.id,
                    "nome": c.nome,
                    "valor": c.valor,
                    "vencimento": c.data_vencimento.isoformat(),
                    "dias": dias,
                    "quando": "hoje" if dias == 0 else f"em {dias} dia(s)",
                }
            )
        for r in receber_due_for_reminder(db, ContaReceber, dias):
            if r.id in seen_r:
                continue
            seen_r.add(r.id)
            receber_out.append(
                {
                    "id": r.id,
                    "nome": r.nome,
                    "valor": r.valor,
                    "data": r.data_esperada.isoformat(),
                    "dias": dias,
                }
            )

    contas_out.sort(key=lambda x: x["vencimento"])
    receber_out.sort(key=lambda x: x["data"])
    return jsonify(
        {
            "enabled": enabled,
            "hoje": hoje.isoformat(),
            "contas": contas_out,
            "receber": receber_out,
        }
    )


@bp.route("/api/boleto/parsear", methods=["POST"])
@limiter.limit("20 per minute")
def api_boleto_parsear():
    from theoos.boleto import parse_linha_digitavel

    dados = request.get_json(silent=True) or {}
    linha = dados.get("linha", "")
    try:
        info = parse_linha_digitavel(linha)
    except ValueError as e:
        return jsonify({"sucesso": False, "erro": str(e)}), 400
    return jsonify(
        {
            "sucesso": True,
            "valor": info["valor"],
            "vencimento": info["vencimento"].isoformat() if info["vencimento"] else None,
            "banco": info["banco"],
            "nosso_numero": info["nosso_numero"],
        }
    )
