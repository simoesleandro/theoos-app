"""Detetive de preços 2.0 — cesta, alertas, hábitos."""
import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_

_TOKEN_RE = re.compile(r'\w+', re.UNICODE)


def _tokenize(texto):
    """Extrai tokens (palavras) de um texto, removendo acentos para busca."""
    if not texto:
        return []
    from unicodedata import normalize as _norm
    normalized = _norm('NFKD', texto.lower()).encode('ascii', 'ignore').decode('ascii')
    return [t for t in _TOKEN_RE.findall(normalized) if len(t) >= 2]


def _token_match_score(tokens, nome, nome_normalizado, marca):
    """Quantos tokens casam nos campos de busca. Retorna 0 se nenhum."""
    score = 0
    nome_l = (nome or '').lower()
    norm_l = (nome_normalizado or '').lower()
    marca_l = (marca or '').lower()
    texto_unificado = f"{nome_l} {norm_l} {marca_l}"
    for tok in tokens:
        if tok in texto_unificado:
            score += 1
    return score


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


def _norm_unidade(unidade):
    """Normaliza unidade de medida — padroniza variações comuns."""
    u = (unidade or "un").strip().lower()
    mapping = {
        "l": "l", "lt": "l", "litro": "l", "litros": "l",
        "ml": "ml", "mililitro": "ml", "mililitros": "ml",
        "kg": "kg", "kilo": "kg", "quilo": "kg", "kilograma": "kg",
        "g": "g", "gr": "g", "grama": "g", "gramas": "g",
        "un": "un", "und": "un", "unid": "un", "unidade": "un", "unidades": "un",
        "cx": "cx", "caixa": "cx", "caixas": "cx",
        "pct": "pct", "pacote": "pct", "pacotes": "pct",
        "frasco": "un", "frc": "un",
        "lt": "l",
        "lata": "un", "latinha": "un",
        "garrafa": "un", "gf": "un", "garrafinha": "un",
        "sache": "un", "sch": "un",
    }
    return mapping.get(u, u)


def _unit_price(item):
    """Preço por unidade de medida (total ÷ quantidade)."""
    qtd = float(item.quantidade or 0)
    if qtd > 0 and item.valor_total is not None:
        return float(item.valor_total) / qtd
    return float(item.valor_unitario or 0)


def _pair_last_two_purchases(regs):
    """Última compra vs compra anterior em data diferente."""
    if len(regs) < 2:
        return None, None
    recente = regs[0]
    anterior = None
    for reg in regs[1:]:
        if reg.nota and recente.nota and reg.nota.data.date() != recente.nota.data.date():
            anterior = reg
            break
    return recente, anterior


def _price_variation_entry(nome, recente, anterior):
    """Compara duas compras com mesma unidade e preço unitário normalizado."""
    if not recente or not anterior:
        return None
    if _norm_unidade(recente.unidade) != _norm_unidade(anterior.unidade):
        return None
    if (recente.quantidade or 0) <= 0 or (anterior.quantidade or 0) <= 0:
        return None

    preco_recente = _unit_price(recente)
    preco_anterior = _unit_price(anterior)
    if preco_anterior <= 0:
        return None

    diff = preco_recente - preco_anterior
    pct = (diff / preco_anterior) * 100
    unidade = _norm_unidade(recente.unidade)

    return {
        "produto": nome,
        "preco_recente": round(preco_recente, 4),
        "preco_anterior": round(preco_anterior, 4),
        "data_recente": recente.nota.data if recente.nota else None,
        "data_anterior": anterior.nota.data if anterior.nota else None,
        "qtd_recente": recente.quantidade,
        "qtd_anterior": anterior.quantidade,
        "total_recente": recente.valor_total,
        "total_anterior": anterior.valor_total,
        "unidade": unidade,
        "variacao": round(diff, 4),
        "percentual": pct,
        "pct": pct,
        "subiu": diff > 0,
    }


def price_variations(db, ItemGasto, Financas, limit=5, min_pct=5.0, min_diff=0.01):
    """Variação de preço unitário entre duas compras em datas diferentes."""
    itens = (
        ItemGasto.query.join(Financas)
        .filter(Financas.tipo == "debito")
        .order_by(Financas.data.desc())
        .all()
    )
    historico = defaultdict(list)
    for it in itens:
        nome = it.nome_normalizado or it.nome
        chave = (nome, _norm_unidade(it.unidade))
        historico[chave].append(it)

    variacoes = []
    for (nome, _un), regs in historico.items():
        recente, anterior = _pair_last_two_purchases(regs)
        entry = _price_variation_entry(nome, recente, anterior)
        if not entry:
            continue
        if abs(entry["variacao"]) < min_diff:
            continue
        if abs(entry["percentual"]) < min_pct:
            continue
        variacoes.append(entry)

    variacoes.sort(key=lambda x: abs(x["variacao"]), reverse=True)
    return variacoes[:limit]


def price_spike_alerts(db, ItemGasto, Financas, min_pct=10.0):
    """Produtos com alta relevante entre duas compras (preço unitário normalizado)."""
    raw = price_variations(db, ItemGasto, Financas, limit=8, min_pct=min_pct)
    return [
        {
            "produto": v["produto"],
            "preco_recente": v["preco_recente"],
            "preco_anterior": v["preco_anterior"],
            "pct": v["pct"],
            "subiu": v["subiu"],
        }
        for v in raw
    ]


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
        if (it.quantidade or 0) <= 0:
            continue
        by_store[_item_mercado(it)].append(_unit_price(it))

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


def _pesquisa_dedupe_key(it, preco_u):
    nome = (it.nome_normalizado or it.nome or "").strip().lower()
    marca = (it.marca or "").strip().lower()
    return (
        it.financa_id,
        nome,
        marca,
        _norm_unidade(it.unidade),
        round(float(it.quantidade or 0), 3),
        round(preco_u, 4),
        round(float(it.valor_total or 0), 2),
    )


def pesquisa_resultados(db, ItemGasto, Financas, termo, Produto=None):
    """Histórico de busca com preço unitário e ranqueamento por token.
    
    Divide o termo em palavras-chave e pontua cada item por quantas
    palavras casam nos campos (nome, nome_normalizado, marca, aliases).
    Ordena por relevância (score) decrescente, depois por data.
    
    Itens vinculados ao mesmo produto_id no catálogo são agrupados
    independentemente da grafia OCR original.
    """
    if not termo or not termo.strip():
        return []
    t = termo.strip()
    tokens = _tokenize(t)
    if not tokens:
        return []

    produto_ids_alias = set()
    if Produto is not None:
        try:
            import json
            all_prods = Produto.query.all()
            for p in all_prods:
                aliases = []
                if p.aliases:
                    try:
                        aliases = json.loads(p.aliases) if isinstance(p.aliases, str) else p.aliases
                    except (json.JSONDecodeError, TypeError):
                        aliases = []
                if _token_match_score(tokens, p.nome, p.nome, '') > 0:
                    produto_ids_alias.add(p.id)
                    continue
                for a in aliases:
                    if _token_match_score(tokens, a, a, '') > 0:
                        produto_ids_alias.add(p.id)
                        break
        except Exception:
            pass

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

    if produto_ids_alias:
        itens_extra = (
            ItemGasto.query.join(Financas)
            .filter(
                Financas.tipo == "debito",
                ItemGasto.produto_id.in_(produto_ids_alias),
                ~ItemGasto.id.in_([i.id for i in itens]),
            )
            .all()
        )
        itens = itens + itens_extra

    seen = set()
    rows = []
    for it in itens:
        if (it.quantidade or 0) <= 0:
            continue
        preco_u = round(_unit_price(it), 4)
        key = _pesquisa_dedupe_key(it, preco_u)
        if key in seen:
            continue
        seen.add(key)

        nome_canonico = it.nome_normalizado or it.nome
        if getattr(it, "produto_id", None) and it.produto and it.produto.nome:
            nome_canonico = it.produto.nome

        score = _token_match_score(
            tokens,
            it.nome or '',
            it.nome_normalizado or '',
            it.marca or '',
        )

        rows.append(
            {
                "id": it.id,
                "nome": it.nome,
                "nome_normalizado": nome_canonico,
                "marca": it.marca,
                "categoria": it.categoria,
                "quantidade": it.quantidade,
                "unidade": _norm_unidade(it.unidade),
                "valor_total": it.valor_total,
                "preco_unitario": preco_u,
                "nota": it.nota,
                "mercado": _item_mercado(it),
                "produto_id": getattr(it, "produto_id", None),
                "score": score,
            }
        )

    rows.sort(key=lambda r: (-r["score"], r["nota"].data if r.get("nota") and r["nota"].data else datetime.min), reverse=False)
    rows[:] = rows[:]  # force stable order before collapse
    return _collapse_pesquisa_rows(rows)


def _collapse_pesquisa_rows(rows):
    """Agrupa mesma compra (data+loja+produto+marca+unidade) em uma linha.
    
    Usa produto_id quando disponível como chave primária de identidade do produto,
    garantindo que itens do mesmo produto canônico agrupem mesmo com nomes OCR distintos.
    """
    grupos = defaultdict(list)
    for r in rows:
        data = r["nota"].data.date() if r.get("nota") and r["nota"].data else None
        pid = r.get("produto_id")
        nome_chave = (r["nome_normalizado"] or "").strip().lower()
        chave = (
            data,
            r["mercado"],
            pid if pid else nome_chave,
            (r["marca"] or "").strip().lower(),
            r["unidade"],
        )
        grupos[chave].append(r)

    out = []
    for items in grupos.values():
        items.sort(key=lambda x: x["preco_unitario"])
        base = dict(items[0])
        if len(items) > 1:
            precos = [i["preco_unitario"] for i in items]
            totais = sorted({round(i["valor_total"], 2) for i in items})
            base["agrupado"] = True
            base["variantes"] = len(items)
            base["preco_min"] = min(precos)
            base["preco_max"] = max(precos)
            base["totais_distintos"] = totais
            base["preco_unitario"] = min(precos)
            base["valor_total"] = items[0]["valor_total"]
        else:
            base["agrupado"] = False
        out.append(base)

    out.sort(
        key=lambda x: (
            -(x.get("score", 0)),
            -(x["nota"].data.timestamp() if x.get("nota") and x["nota"].data else 0),
        ),
    )
    return out


def minmax_por_unidade(resultados):
    """Menor/maior preço unitário agrupado por unidade de medida."""
    grupos = defaultdict(list)
    for r in resultados:
        grupos[r["unidade"]].append(r["preco_unitario"])
        if r.get("agrupado") and r.get("preco_max") is not None:
            grupos[r["unidade"]].append(r["preco_max"])
    out = {}
    for un, precos in grupos.items():
        if not precos:
            continue
        out[un] = {"min": min(precos), "max": max(precos), "count": len(precos)}
    return out


def market_prices_for_term(db, ItemGasto, Financas, termo, limit=12, Produto=None):
    """Último preço unitário por mercado e unidade para um produto.
    
    Usa busca por token: divide o termo em palavras e casa nos campos.
    Quando Produto é fornecido, também busca por aliases do catálogo.
    """
    if not termo or not termo.strip():
        return []
    t = termo.strip()
    tokens = _tokenize(t)
    if not tokens:
        return []

    produto_ids_alias = set()
    if Produto is not None:
        try:
            import json
            all_prods = Produto.query.all()
            for p in all_prods:
                aliases = []
                if p.aliases:
                    try:
                        aliases = json.loads(p.aliases) if isinstance(p.aliases, str) else p.aliases
                    except (json.JSONDecodeError, TypeError):
                        aliases = []
                if _token_match_score(tokens, p.nome, p.nome, '') > 0:
                    produto_ids_alias.add(p.id)
                    continue
                for a in aliases:
                    if _token_match_score(tokens, a, a, '') > 0:
                        produto_ids_alias.add(p.id)
                        break
        except Exception:
            pass

    filters = [
        Financas.tipo == "debito",
        or_(
            ItemGasto.nome.ilike(f"%{t}%"),
            ItemGasto.nome_normalizado.ilike(f"%{t}%"),
            ItemGasto.marca.ilike(f"%{t}%"),
        ),
    ]
    if produto_ids_alias:
        filters[1] = or_(filters[1], ItemGasto.produto_id.in_(produto_ids_alias))

    itens = (
        ItemGasto.query.join(Financas)
        .filter(*filters)
        .order_by(Financas.data.desc())
        .all()
    )
    by_store_unit = {}
    for it in itens:
        if (it.quantidade or 0) <= 0:
            continue
        score = _token_match_score(tokens, it.nome or '', it.nome_normalizado or '', it.marca or '')
        loja = _item_mercado(it)
        un = _norm_unidade(it.unidade)
        chave = (loja, un)
        if chave in by_store_unit:
            existing_score = by_store_unit[chave].get("_score", 0)
            if score <= existing_score:
                continue
        by_store_unit[chave] = {
            "loja": loja,
            "unidade": un,
            "preco": round(_unit_price(it), 2),
            "produto": it.nome_normalizado or it.nome,
            "quantidade": it.quantidade,
            "data": it.nota.data.strftime("%d/%m/%Y") if it.nota else "",
            "_score": score,
        }
    rows = list(by_store_unit.values())
    rows.sort(key=lambda x: (-x.pop("_score", 0), x["preco"]))
    return rows[:limit]


def monthly_spending_by_category(db, Financas, ItemGasto, meses=6, top_n=5):
    """Tendência mensal (últimos N meses, incluindo o atual) para as top-N categorias.

    Returns:
        list[dict] com chaves:
            categoria: str
            total: float (gasto total no período)
            serie: list[dict] [{mes: 'YYYY-MM', valor: float}]
            variacao_pct: float (variação do último mês vs penúltimo)
    """
    hoje = date.today()
    y, m = hoje.year, hoje.month
    meses_lista: list[date] = []
    for _ in range(meses):
        meses_lista.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    meses_lista.reverse()
    primeiro = meses_lista[0]
    _, ultimo_dia = monthrange(hoje.year, hoje.month)
    ultimo = datetime(hoje.year, hoje.month, ultimo_dia, 23, 59, 59)

    top_cats = (
        db.session.query(
            ItemGasto.categoria,
            func.coalesce(func.sum(ItemGasto.valor_total), 0.0).label("total"),
        )
        .join(Financas)
        .filter(Financas.tipo == "debito", Financas.data >= primeiro, Financas.data <= ultimo)
        .group_by(ItemGasto.categoria)
        .order_by(func.sum(ItemGasto.valor_total).desc())
        .limit(top_n)
        .all()
    )
    top_cats_list = [r[0] for r in top_cats]

    serie_lookup: dict[tuple[str, str], float] = {}
    if top_cats_list:
        rows = (
            db.session.query(
                ItemGasto.categoria,
                func.strftime("%Y-%m", Financas.data).label("mes"),
                func.coalesce(func.sum(ItemGasto.valor_total), 0.0).label("total"),
            )
            .join(Financas)
            .filter(
                Financas.tipo == "debito",
                Financas.data >= primeiro,
                Financas.data <= ultimo,
                ItemGasto.categoria.in_(top_cats_list),
            )
            .group_by(ItemGasto.categoria, func.strftime("%Y-%m", Financas.data))
            .all()
        )
        for cat, mes_str, total in rows:
            serie_lookup[(cat, mes_str)] = float(total)

    resultados: list[dict] = []
    for cat in top_cats_list:
        serie: list[dict] = []
        for mes in meses_lista:
            mes_str = mes.strftime("%Y-%m")
            val = serie_lookup.get((cat, mes_str), 0.0)
            serie.append({"mes": mes_str, "valor": val})
        if len(serie) >= 2 and serie[-1]["valor"] > 0:
            ant = serie[-2]["valor"]
            atual = serie[-1]["valor"]
            variacao = ((atual - ant) / ant * 100) if ant > 0 else 0.0
        else:
            variacao = 0.0
        resultados.append(
            {
                "categoria": cat,
                "total": sum(s["valor"] for s in serie),
                "serie": serie,
                "variacao_pct": round(variacao, 1),
            }
        )
    return resultados


def forecast_next_month(db, Financas, ItemGasto, meses_historico=3, top_n=5):
    """Projeção simples de gastos do próximo mês por categoria.

    Usa média ponderada dos últimos N meses (peso 3 / 2 / 1) para o mês mais
    recente ter mais influência. Retorna top-N categorias + total projetado.
    Útil para alertas de orçamento ("Supermercado vai estourar R$ X").

    Returns:
        {
            "mes_projecao": "YYYY-MM",
            "total": float,
            "categorias": [{categoria, projecao, media_3m, historico}, ...],
            "metodo": "media_ponderada_3m",
        }
    """
    hoje = date.today()
    if hoje.month == 12:
        prox_y, prox_m = hoje.year + 1, 1
    else:
        prox_y, prox_m = hoje.year, hoje.month + 1
    mes_proj = f"{prox_y:04d}-{prox_m:02d}"

    y, m = hoje.year, hoje.month
    meses_hist: list[date] = []
    for _ in range(meses_historico):
        meses_hist.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    pesos = [1, 2, 3]  # mais recente = maior peso
    soma_pesos = sum(pesos)

    top_cats = (
        db.session.query(
            ItemGasto.categoria,
            func.coalesce(func.sum(ItemGasto.valor_total), 0.0).label("total"),
        )
        .join(Financas)
        .filter(Financas.tipo == "debito")
        .group_by(ItemGasto.categoria)
        .order_by(func.sum(ItemGasto.valor_total).desc())
        .limit(top_n)
        .all()
    )

    categorias = []
    total = 0.0
    for cat, _ in top_cats:
        serie: list[float] = []
        historico = []
        for mes in reversed(meses_hist):
            last_day = monthrange(mes.year, mes.month)[1]
            dt_ini = datetime(mes.year, mes.month, 1)
            dt_fim = datetime(mes.year, mes.month, last_day, 23, 59, 59)
            val = (
                db.session.query(func.coalesce(func.sum(ItemGasto.valor_total), 0.0))
                .join(Financas)
                .filter(
                    Financas.tipo == "debito",
                    Financas.data >= dt_ini,
                    Financas.data <= dt_fim,
                    ItemGasto.categoria == cat,
                )
                .scalar()
                or 0.0
            )
            serie.append(float(val))
            historico.append({"mes": mes.strftime("%Y-%m"), "valor": float(val)})
        if any(s > 0 for s in serie):
            projecao = sum(s * p for s, p in zip(serie, pesos)) / soma_pesos
        else:
            projecao = 0.0
        categorias.append(
            {
                "categoria": cat,
                "projecao": round(projecao, 2),
                "media_3m": round(sum(serie) / len(serie), 2) if serie else 0.0,
                "historico": historico,
            }
        )
        total += projecao

    return {
        "mes_projecao": mes_proj,
        "total": round(total, 2),
        "categorias": categorias,
        "metodo": f"media_ponderada_{meses_historico}m",
    }


def produto_price_history(db, ItemGasto, Financas, Produto, produto_id):
    """Histórico completo de preços de um produto do catálogo.
    
    Retorna todas as compras vinculadas ao produto_id, com preço unitário,
    agrupadas por data+mercado, ordenadas da mais recente para a mais antiga.
    Inclui estatísticas: menor preço, maior preço, preço médio, tendência.
    """
    produto = db.session.get(Produto, produto_id)
    if not produto:
        return None

    itens = (
        ItemGasto.query.join(Financas)
        .filter(
            Financas.tipo == "debito",
            ItemGasto.produto_id == produto_id,
            ItemGasto.quantidade > 0,
        )
        .order_by(Financas.data.desc())
        .all()
    )

    if not itens:
        return {
            "produto": {"id": produto.id, "nome": produto.nome, "marca": produto.marca, "categoria": produto.categoria, "unidade": produto.unidade},
            "compras": [],
            "estatisticas": None,
            "por_mercado": [],
        }

    compras = []
    precos = []
    for it in itens:
        pu = _unit_price(it)
        precos.append(pu)
        compras.append({
            "data": it.nota.data.strftime("%d/%m/%Y") if it.nota else "",
            "data_iso": it.nota.data.isoformat() if it.nota else "",
            "mercado": _item_mercado(it),
            "quantidade": float(it.quantidade or 0),
            "unidade": _norm_unidade(it.unidade),
            "preco_unitario": round(pu, 2),
            "valor_total": float(it.valor_total or 0),
            "marca": it.marca or "",
        })

    stat = {
        "menor_preco": round(min(precos), 2) if precos else 0,
        "maior_preco": round(max(precos), 2) if precos else 0,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0,
        "total_compras": len(precos),
        "tendencia": "estavel",
    }
    if len(precos) >= 2:
        recentes = precos[: min(3, len(precos))]
        antigas = precos[-min(3, len(precos)) :]
        media_recente = sum(recentes) / len(recentes)
        media_antiga = sum(antigas) / len(antigas)
        if media_antiga > 0:
            pct = (media_recente - media_antiga) / media_antiga * 100
            stat["variacao_pct"] = round(pct, 1)
            stat["tendencia"] = "subiu" if pct > 5 else ("caiu" if pct < -5 else "estavel")
        else:
            stat["variacao_pct"] = 0

    lojas = defaultdict(list)
    for c in compras:
        lojas[c["mercado"]].append(c["preco_unitario"])
    por_mercado = []
    for loja, ps in lojas.items():
        por_mercado.append({
            "loja": loja,
            "preco_medio": round(sum(ps) / len(ps), 2),
            "menor": min(ps),
            "maior": max(ps),
            "compras": len(ps),
        })
    por_mercado.sort(key=lambda x: x["preco_medio"])

    return {
        "produto": {"id": produto.id, "nome": produto.nome, "marca": produto.marca, "categoria": produto.categoria, "unidade": produto.unidade},
        "compras": compras,
        "estatisticas": stat,
        "por_mercado": por_mercado,
    }
