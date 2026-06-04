"""Detetive de preços 2.0 — cesta, alertas, hábitos."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import or_


def _mercado_from_nota(descricao):
    if not descricao:
        return "Outro"
    d = descricao.replace("IA: ", "").replace("Compra: ", "").strip()
    return d[:80] if d else "Outro"


def last_price_by_product(db, ItemGasto, Financas):
    """Último preço unitário e mercado por nome normalizado."""
    itens = (
        ItemGasto.query.join(Financas)
        .filter(Financas.tipo == "debito")
        .order_by(Financas.data.desc())
        .all()
    )
    by_name = {}
    for it in itens:
        key = (it.nome_normalizado or it.nome or "").strip().lower()
        if not key or key in by_name:
            continue
        mercado = getattr(it, "mercado", None) or _mercado_from_nota(
            it.nota.descricao if it.nota else ""
        )
        by_name[key] = {
            "nome": it.nome_normalizado or it.nome,
            "preco": it.valor_unitario,
            "mercado": mercado,
            "data": it.nota.data if it.nota else None,
        }
    return by_name


def basket_estimates_by_store(db, ListaCompras, ItemGasto, Financas):
    """Estima total da lista pendente por mercado do histórico."""
    pendentes = ListaCompras.query.filter_by(status="pendente").all()
    if not pendentes:
        return []

    prices = last_price_by_product(db, ItemGasto, Financas)
    by_store = defaultdict(lambda: {"total": 0.0, "itens": 0, "sem_preco": 0})

    for item in pendentes:
        key = item.item.strip().lower()
        info = prices.get(key)
        if not info:
            by_store["Sem histórico"]["sem_preco"] += 1
            continue
        loja = info["mercado"]
        by_store[loja]["total"] += info["preco"] * (item.quantidade or 1)
        by_store[loja]["itens"] += 1

    result = [
        {"loja": loja, "total": v["total"], "itens": v["itens"], "sem_preco": v["sem_preco"]}
        for loja, v in by_store.items()
    ]
    result.sort(key=lambda x: x["total"] if x["total"] > 0 else 1e9)
    return result


def price_spike_alerts(db, ItemGasto, Financas, min_pct=10.0):
    """Produtos com alta relevante entre duas compras em datas diferentes."""
    itens = (
        ItemGasto.query.join(Financas)
        .filter(Financas.tipo == "debito")
        .order_by(Financas.data.desc())
        .all()
    )
    historico = defaultdict(list)
    for it in itens:
        nome = it.nome_normalizado or it.nome
        historico[nome].append(it)

    alertas = []
    for nome, regs in historico.items():
        if len(regs) < 2:
            continue
        recente = regs[0]
        anterior = None
        for reg in regs[1:]:
            if reg.nota and recente.nota and reg.nota.data.date() != recente.nota.data.date():
                anterior = reg
                break
        if not anterior or anterior.valor_unitario <= 0:
            continue
        diff = recente.valor_unitario - anterior.valor_unitario
        pct = (diff / anterior.valor_unitario) * 100
        if abs(pct) >= min_pct:
            alertas.append(
                {
                    "produto": nome,
                    "preco_recente": recente.valor_unitario,
                    "preco_anterior": anterior.valor_unitario,
                    "pct": pct,
                    "subiu": diff > 0,
                }
            )
    alertas.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return alertas[:8]


def missing_habit_products(db, ItemGasto, Financas, days=45):
    """Produtos comprados com frequência que sumiram do histórico recente."""
    limite = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    itens = (
        ItemGasto.query.join(Financas)
        .filter(Financas.tipo == "debito")
        .order_by(Financas.data.desc())
        .all()
    )
    contagem = defaultdict(list)
    for it in itens:
        nome = it.nome_normalizado or it.nome
        contagem[nome].append(it.nota.data if it.nota else None)

    sugestoes = []
    for nome, datas in contagem.items():
        if len(datas) < 2:
            continue
        ultima = max(d for d in datas if d)
        if ultima < limite:
            sugestoes.append({"produto": nome, "ultima_compra": ultima, "vezes": len(datas)})
    sugestoes.sort(key=lambda x: x["vezes"], reverse=True)
    return sugestoes[:6]


def budget_status(db, Orcamento, ItemGasto, Financas):
    """% do orçamento por categoria no mês."""
    hoje = date.today()
    primeiro = datetime.combine(date(hoje.year, hoje.month, 1), datetime.min.time())
    orcamentos = Orcamento.query.all()
    out = []
    for o in orcamentos:
        gasto = (
            db.session.query(db.func.sum(ItemGasto.valor_total))
            .join(Financas)
            .filter(
                ItemGasto.categoria == o.categoria,
                Financas.data >= primeiro,
                Financas.tipo == "debito",
            )
            .scalar()
            or 0.0
        )
        pct = (gasto / o.limite_mensal * 100) if o.limite_mensal > 0 else 0
        meta = getattr(o, "meta_economia", None) or 0
        out.append(
            {
                "categoria": o.categoria,
                "gasto": gasto,
                "limite": o.limite_mensal,
                "pct": pct,
                "meta_economia": meta,
                "alerta": pct >= 80,
            }
        )
    out.sort(key=lambda x: x["pct"], reverse=True)
    return out


def week_agenda(db, Conta, ContaReceber, hoje=None, days=7):
    hoje = hoje or date.today()
    limite = hoje + timedelta(days=days)
    contas = (
        Conta.query.filter(
            Conta.status == "pendente",
            Conta.data_vencimento <= limite,
        )
        .order_by(Conta.data_vencimento)
        .all()
    )
    receber = (
        ContaReceber.query.filter(
            ContaReceber.status == "pendente",
            ContaReceber.data_esperada <= limite,
        )
        .order_by(ContaReceber.data_esperada)
        .all()
    )
    return {
        "contas": contas,
        "receber": receber,
        "total_pagar": sum(c.valor for c in contas),
        "total_receber": sum(r.valor for r in receber),
    }


def budget_savings_progress(gasto, limite, meta_economia):
    """Progresso da meta de economia: quanto 'sobrou' vs meta definida."""
    meta = meta_economia or 0
    if meta <= 0:
        return None
    economia = max(limite - gasto, 0.0)
    pct = min(economia / meta * 100, 100) if meta > 0 else 0
    return {
        "economia": economia,
        "meta": meta,
        "pct": pct,
        "atingiu": economia >= meta,
    }


def _item_mercado(it):
    return getattr(it, "mercado", None) or _mercado_from_nota(
        it.nota.descricao if it.nota else ""
    )


def market_ranking_global(db, ItemGasto, Financas, min_samples=2, limit=10):
    """Ranking de mercados por preço médio unitário (histórico geral)."""
    itens = (
        ItemGasto.query.join(Financas)
        .filter(Financas.tipo == "debito")
        .all()
    )
    by_store = defaultdict(list)
    for it in itens:
        by_store[_item_mercado(it)].append(it.valor_unitario)

    rows = []
    for loja, precos in by_store.items():
        if len(precos) < min_samples:
            continue
        media = sum(precos) / len(precos)
        rows.append(
            {
                "loja": loja,
                "media": round(media, 2),
                "amostras": len(precos),
                "minimo": round(min(precos), 2),
            }
        )
    rows.sort(key=lambda x: x["media"])
    return rows[:limit]


def market_prices_for_term(db, ItemGasto, Financas, termo, limit=12):
    """Último preço registrado por mercado para um produto (busca)."""
    if not termo or not termo.strip():
        return []
    t = termo.strip()
    itens = (
        ItemGasto.query.join(Financas)
        .filter(
            Financas.tipo == "debito",
            or_(
                ItemGasto.nome.ilike(f"%{t}%"),
                ItemGasto.nome_normalizado.ilike(f"%{t}%"),
                ItemGasto.marca.ilike(f"%{t}%"),
            ),
        )
        .order_by(Financas.data.desc())
        .all()
    )
    by_store = {}
    for it in itens:
        loja = _item_mercado(it)
        if loja in by_store:
            continue
        by_store[loja] = {
            "loja": loja,
            "preco": round(it.valor_unitario, 2),
            "produto": it.nome_normalizado or it.nome,
            "data": it.nota.data.strftime("%d/%m/%Y") if it.nota else "",
        }
    rows = list(by_store.values())
    rows.sort(key=lambda x: x["preco"])
    return rows[:limit]
