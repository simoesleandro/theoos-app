"""Catálogo canônico e matching de produtos (pós-OCR)."""
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

# Tokens genéricos que não distinguem produtos
_NOISE = frozenset({
    "de", "da", "do", "das", "dos", "com", "sem", "para", "tipo",
    "pct", "unid", "und", "embalagem", "ref", "cod",
})

# Unidades/abreviações que podem aparecer no fim da descrição do cupom
_UNIT_TOKENS = frozenset({"un", "kg", "g", "l", "ml", "cx", "pct", "und"})

AUTO_MATCH_THRESHOLD = 0.82


def _strip_accents(text):
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize_key(text):
    """Texto comparável: minúsculas, sem acento, só alfanumérico."""
    if not text:
        return ""
    text = _strip_accents(text).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def norm_unidade(unidade):
    u = (unidade or "un").strip().lower()
    if u in ("l",):
        return "l"
    if u in ("cx", "caixa"):
        return "cx"
    return u


def _token_set(text):
    return set(normalize_key(text).split()) - _NOISE


def _jaccard(a, b):
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def combined_similarity(a, b):
    """Similaridade 0–1 entre duas descrições de produto."""
    if not a or not b:
        return 0.0
    na, nb = normalize_key(a), normalize_key(b)
    if na == nb:
        return 1.0

    ta, tb = _token_set(a), _token_set(b)
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    ts, tl = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    extra = tl - ts - _UNIT_TOKENS
    if shorter in longer and len(extra) <= 1:
        return 0.92

    j = _jaccard(a, b)
    r = SequenceMatcher(None, na, nb).ratio()
    return max(j, r, j * 0.55 + r * 0.45)


def parse_aliases(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(a).strip() for a in raw if str(a).strip()]
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(a).strip() for a in data if str(a).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [a.strip() for a in str(raw).split(",") if a.strip()]


def dump_aliases(aliases):
    cleaned = sorted({a.strip() for a in aliases if a and a.strip()})
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def _produto_key(nome, marca, unidade):
    return (
        normalize_key(nome),
        normalize_key(marca or ""),
        norm_unidade(unidade),
    )


def _score_entry(text, entry, unidade=None, marca=None):
    if not text:
        return 0.0
    candidates = [entry["nome"]] + entry.get("aliases", [])
    best = max(combined_similarity(text, c) for c in candidates if c)

    if unidade and entry.get("unidade"):
        if norm_unidade(unidade) != norm_unidade(entry["unidade"]):
            best *= 0.88

    if marca and entry.get("marca"):
        if normalize_key(marca) != normalize_key(entry["marca"]):
            best *= 0.96

    return best


def _entry_from_produto(p):
    return {
        "id": p.id,
        "nome": p.nome,
        "marca": (p.marca or "").strip() or None,
        "unidade": p.unidade or "un",
        "categoria": p.categoria or "Outros",
        "aliases": parse_aliases(p.aliases),
    }


def build_catalog_from_produto(db, Produto, limit=150):
    rows = Produto.query.order_by(Produto.nome).limit(limit).all()
    return [_entry_from_produto(p) for p in rows]


def build_catalog_from_history(db, ItemGasto, limit=150):
    from sqlalchemy import func

    rows = (
        db.session.query(
            ItemGasto.nome_normalizado,
            ItemGasto.marca,
            ItemGasto.unidade,
            ItemGasto.categoria,
            func.count(ItemGasto.id).label("cnt"),
        )
        .filter(
            ItemGasto.nome_normalizado.isnot(None),
            ItemGasto.nome_normalizado != "",
        )
        .group_by(
            ItemGasto.nome_normalizado,
            ItemGasto.marca,
            ItemGasto.unidade,
            ItemGasto.categoria,
        )
        .order_by(func.count(ItemGasto.id).desc())
        .limit(limit)
        .all()
    )

    catalog = []
    seen_names = set()
    for row in rows:
        canonical = (row.nome_normalizado or "").strip()
        if not canonical:
            continue
        key = normalize_key(canonical)
        if key in seen_names:
            continue
        seen_names.add(key)

        alias_rows = (
            db.session.query(ItemGasto.nome)
            .filter(ItemGasto.nome_normalizado == canonical)
            .distinct()
            .limit(25)
            .all()
        )
        aliases = []
        for (raw,) in alias_rows:
            raw = (raw or "").strip()
            if raw and normalize_key(raw) != key:
                aliases.append(raw)

        catalog.append({
            "nome": canonical,
            "marca": (row.marca or "").strip() or None,
            "unidade": row.unidade or "un",
            "categoria": row.categoria or "Outros",
            "aliases": aliases,
        })
    return catalog


def build_catalog(db, ItemGasto, Produto=None, limit=150):
    """Catálogo para matching: preferência pela tabela Produto."""
    if Produto is not None:
        try:
            if Produto.query.first():
                return build_catalog_from_produto(db, Produto, limit)
        except Exception:
            pass
    return build_catalog_from_history(db, ItemGasto, limit)


def catalog_prompt_block(catalog, limit=60):
    """Bloco de texto para injetar no prompt do Gemini."""
    if not catalog:
        return ""
    lines = []
    for entry in catalog[:limit]:
        marca = f", marca {entry['marca']}" if entry.get("marca") else ""
        lines.append(f"- {entry['nome']} ({entry['unidade']}{marca})")
    return (
        "\nProdutos já cadastrados no sistema (IMPORTANTE: se o item comprado for "
        "equivalente a um destes, use EXATAMENTE o mesmo nome_normalizado):\n"
        + "\n".join(lines)
        + "\n"
    )


def resolve_nome_normalizado(nome_bruto, nome_ia, marca, unidade, catalog):
    """
    Retorna (nome_normalizado, entrada_catalogo ou None).
    Cruza sugestão da IA com o histórico para evitar duplicatas.
    """
    cand = (nome_ia or "").strip() or (nome_bruto or "").strip()
    if not cand:
        return "Desconhecido", None
    if not catalog:
        return cand, None

    best_entry = None
    best_score = 0.0
    for entry in catalog:
        for text in (cand, (nome_bruto or "").strip()):
            score = _score_entry(text, entry, unidade, marca)
            if score > best_score:
                best_score = score
                best_entry = entry

    if best_entry and best_score >= AUTO_MATCH_THRESHOLD:
        return best_entry["nome"], best_entry
    return cand, None


def find_produto_by_nome(db, Produto, nome, marca=None, unidade=None):
    """Busca produto canônico por nome normalizado."""
    key = _produto_key(nome, marca, unidade)
    for p in Produto.query.all():
        if _produto_key(p.nome, p.marca, p.unidade) == key:
            return p
    nome_key = normalize_key(nome)
    for p in Produto.query.all():
        if normalize_key(p.nome) == nome_key:
            if marca and p.marca and normalize_key(marca) != normalize_key(p.marca):
                continue
            if unidade and norm_unidade(unidade) != norm_unidade(p.unidade):
                continue
            return p
    return None


def _add_alias(produto, alias):
    if not alias:
        return
    alias = alias.strip()
    if not alias or normalize_key(alias) == normalize_key(produto.nome):
        return
    aliases = parse_aliases(produto.aliases)
    if alias not in aliases:
        aliases.append(alias)
        produto.aliases = dump_aliases(aliases)


def ensure_produto(db, Produto, nome_normalizado, nome_bruto=None, marca=None, unidade=None, categoria=None, matched_entry=None):
    """Retorna produto_id — cria ou reutiliza entrada no catálogo."""
    nome = (nome_normalizado or "").strip()
    if not nome:
        return None

    if matched_entry and matched_entry.get("id"):
        produto = db.session.get(Produto, matched_entry["id"])
        if produto:
            _add_alias(produto, nome_bruto)
            return produto.id

    produto = find_produto_by_nome(db, Produto, nome, marca, unidade)
    if produto:
        _add_alias(produto, nome_bruto)
        return produto.id

    aliases = []
    raw = (nome_bruto or "").strip()
    if raw and normalize_key(raw) != normalize_key(nome):
        aliases.append(raw)

    produto = Produto(
        nome=nome,
        marca=(marca or "").strip() or None,
        unidade=unidade or "un",
        categoria=categoria or "Outros",
        aliases=dump_aliases(aliases),
    )
    db.session.add(produto)
    db.session.flush()
    return produto.id


def normalize_itens_ocr(db, ItemGasto, itens_lista, Produto=None):
    """Aplica matching de catálogo a cada item extraído pelo OCR."""
    catalog = build_catalog(db, ItemGasto, Produto)
    for item in itens_lista:
        nome_norm, matched = resolve_nome_normalizado(
            item.get("nome", ""),
            item.get("nome_normalizado"),
            item.get("marca"),
            item.get("unidade"),
            catalog,
        )
        item["nome_normalizado"] = nome_norm
        if matched:
            if not item.get("marca") and matched.get("marca"):
                item["marca"] = matched["marca"]
            if item.get("categoria") in (None, "", "Outros") and matched.get("categoria"):
                item["categoria"] = matched["categoria"]
            if not item.get("unidade") or item.get("unidade") == "un":
                item["unidade"] = matched.get("unidade") or item.get("unidade")

        if Produto is not None:
            item["produto_id"] = ensure_produto(
                db,
                Produto,
                nome_norm,
                nome_bruto=item.get("nome"),
                marca=item.get("marca"),
                unidade=item.get("unidade"),
                categoria=item.get("categoria"),
                matched_entry=matched,
            )
    return itens_lista


def seed_catalog_from_history(db, Produto, ItemGasto):
    """Popula catálogo a partir do histórico (executado uma vez)."""
    if Produto.query.first() is not None:
        return 0

    items = ItemGasto.query.filter(
        ItemGasto.nome_normalizado.isnot(None),
        ItemGasto.nome_normalizado != "",
    ).all()

    groups = defaultdict(lambda: {
        "nome": None,
        "marca": None,
        "unidade": "un",
        "categoria": "Outros",
        "aliases": set(),
        "item_ids": [],
    })

    for it in items:
        nome = (it.nome_normalizado or "").strip()
        if not nome:
            continue
        key = _produto_key(nome, it.marca, it.unidade)
        g = groups[key]
        g["nome"] = nome
        g["marca"] = (it.marca or "").strip() or None
        g["unidade"] = it.unidade or "un"
        g["categoria"] = it.categoria or "Outros"
        raw = (it.nome or "").strip()
        if raw and normalize_key(raw) != normalize_key(nome):
            g["aliases"].add(raw)
        g["item_ids"].append(it.id)

    count = 0
    for g in groups.values():
        produto = Produto(
            nome=g["nome"],
            marca=g["marca"],
            unidade=g["unidade"],
            categoria=g["categoria"],
            aliases=dump_aliases(g["aliases"]),
        )
        db.session.add(produto)
        db.session.flush()
        ItemGasto.query.filter(ItemGasto.id.in_(g["item_ids"])).update(
            {"produto_id": produto.id},
            synchronize_session=False,
        )
        count += 1

    if count:
        db.session.commit()
    return count


def list_produtos_com_stats(db, Produto, ItemGasto):
    """Lista produtos do catálogo com contagem de lançamentos."""
    rows = []
    for p in Produto.query.order_by(Produto.nome).all():
        p.lancamentos_count = ItemGasto.query.filter_by(produto_id=p.id).count()
        p.alias_list = parse_aliases(p.aliases)
        rows.append(p)
    return rows


def update_produto_catalog(db, Produto, ItemGasto, ListaCompras, produto_id, nome, marca, unidade, categoria, aliases_raw):
    """Atualiza produto canônico e propaga para lançamentos vinculados."""
    produto = db.session.get(Produto, produto_id)
    if not produto:
        raise ValueError("Produto não encontrado")

    nome_antigo = produto.nome
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Nome não pode ser vazio")

    aliases = parse_aliases(aliases_raw) if isinstance(aliases_raw, str) else list(aliases_raw or [])
    aliases = [a.strip() for a in aliases if a.strip() and normalize_key(a) != normalize_key(nome)]

    produto.nome = nome
    produto.marca = (marca or "").strip() or None
    produto.unidade = unidade or "un"
    produto.categoria = categoria or "Outros"
    produto.aliases = dump_aliases(aliases)

    ItemGasto.query.filter_by(produto_id=produto_id).update({
        "nome_normalizado": nome,
        "marca": produto.marca,
        "unidade": produto.unidade,
        "categoria": produto.categoria,
    }, synchronize_session=False)

    if nome_antigo.lower() != nome.lower():
        ListaCompras.query.filter(
            db.func.lower(ListaCompras.item) == db.func.lower(nome_antigo.strip())
        ).update({
            "item": nome,
            "marca": produto.marca,
            "unidade": produto.unidade,
            "categoria": produto.categoria,
        }, synchronize_session=False)

    db.session.commit()
    return produto


def merge_produtos(db, Produto, ItemGasto, ListaCompras, target_id, source_ids):
    """Unifica produtos duplicados no catálogo."""
    target = db.session.get(Produto, target_id)
    if not target:
        raise ValueError("Produto alvo não encontrado")

    merged_aliases = set(parse_aliases(target.aliases))

    for sid in source_ids:
        sid = int(sid)
        if sid == target_id:
            continue
        source = db.session.get(Produto, sid)
        if not source:
            continue

        old_nome = source.nome
        merged_aliases.add(old_nome)
        merged_aliases.update(parse_aliases(source.aliases))

        ItemGasto.query.filter_by(produto_id=sid).update({
            "produto_id": target_id,
            "nome_normalizado": target.nome,
            "marca": target.marca,
            "unidade": target.unidade,
            "categoria": target.categoria,
        }, synchronize_session=False)

        ItemGasto.query.filter(
            ItemGasto.produto_id.is_(None),
            db.func.lower(ItemGasto.nome_normalizado) == db.func.lower(old_nome.strip()),
        ).update({
            "produto_id": target_id,
            "nome_normalizado": target.nome,
            "marca": target.marca,
            "unidade": target.unidade,
            "categoria": target.categoria,
        }, synchronize_session=False)

        ListaCompras.query.filter(
            db.func.lower(ListaCompras.item) == db.func.lower(old_nome.strip())
        ).update({
            "item": target.nome,
            "marca": target.marca,
            "unidade": target.unidade,
            "categoria": target.categoria,
        }, synchronize_session=False)

        db.session.delete(source)

    merged_aliases.discard(target.nome)
    target.aliases = dump_aliases(merged_aliases)
    db.session.commit()
    return target


def delete_produto_catalog(db, Produto, ItemGasto, produto_id):
    """Remove produto do catálogo (lançamentos ficam sem vínculo)."""
    produto = db.session.get(Produto, produto_id)
    if not produto:
        raise ValueError("Produto não encontrado")
    ItemGasto.query.filter_by(produto_id=produto_id).update(
        {"produto_id": None},
        synchronize_session=False,
    )
    db.session.delete(produto)
    db.session.commit()
