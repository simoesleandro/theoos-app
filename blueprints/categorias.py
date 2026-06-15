"""Blueprint de categorias, produtos e sugestões."""
from __future__ import annotations
from theoos.auth import admin_required

from collections import defaultdict
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from models import Categoria, ItemGasto, ListaCompras, Produto, db
from theoos import produtos as produtos_svc

bp = Blueprint("categorias", __name__)


def _produto_sugestao_dict(nome, marca, unidade, categoria, ultimo_preco):
    return {
        "nome": nome,
        "marca": marca or "",
        "unidade": unidade or "un",
        "categoria": categoria or "Outros",
        "ultimo_preco": ultimo_preco,
    }


def _buscar_sugestoes_produto(q, limit=8):
    seen = set()
    results = []

    catalogo = (
        Produto.query.filter(
            db.or_(
                Produto.nome.ilike(f"%{q}%"),
                Produto.aliases.ilike(f"%{q}%"),
            )
        )
        .order_by(Produto.nome)
        .limit(limit * 2)
        .all()
    )

    for p in catalogo:
        key = (p.nome.lower(), (p.marca or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        ultimo = (
            ItemGasto.query.filter_by(produto_id=p.id)
            .order_by(ItemGasto.id.desc())
            .first()
        )
        preco = ultimo.valor_unitario if ultimo else None
        results.append(
            _produto_sugestao_dict(p.nome, p.marca, p.unidade, p.categoria, preco)
        )
        if len(results) >= limit:
            return results

    gastos = (
        ItemGasto.query.filter(
            db.or_(
                ItemGasto.nome.ilike(f"%{q}%"),
                ItemGasto.nome_normalizado.ilike(f"%{q}%"),
            )
        )
        .order_by(ItemGasto.id.desc())
        .limit(50)
        .all()
    )

    for g in gastos:
        nome = (g.nome_normalizado or g.nome or "").strip()
        if not nome:
            continue
        key = (nome.lower(), (g.marca or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(
            _produto_sugestao_dict(nome, g.marca, g.unidade, g.categoria, g.valor_unitario)
        )
        if len(results) >= limit:
            return results

    lista_itens = (
        ListaCompras.query.filter(ListaCompras.item.ilike(f"%{q}%"))
        .order_by(ListaCompras.id.desc())
        .limit(30)
        .all()
    )

    for lc in lista_itens:
        nome = (lc.item or "").strip()
        if not nome:
            continue
        key = (nome.lower(), (lc.marca or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(_produto_sugestao_dict(nome, lc.marca, lc.unidade, lc.categoria, None))
        if len(results) >= limit:
            break

    return results


@bp.route("/api/categorias", methods=["POST"])
@admin_required
def adicionar_categoria_api():
    dados = request.get_json() or {}
    nome = dados.get("nome", "").strip()
    if not nome:
        return jsonify({"sucesso": False, "erro": "Nome inválido."}), 400

    existente = Categoria.query.filter(db.func.lower(Categoria.nome) == db.func.lower(nome)).first()
    if existente:
        return jsonify({"sucesso": True, "nome": existente.nome, "novo": False})

    try:
        nova_cat = Categoria(nome=nome)
        db.session.add(nova_cat)
        db.session.commit()
        return jsonify({"sucesso": True, "nome": nome, "novo": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": f"Erro ao salvar: {e}"}), 500


@bp.route("/categorias", methods=["GET", "POST"])
def categorias():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("Nome da categoria não pode ser vazio.", "danger")
            return redirect(url_for("categorias.categorias"))
        existente = Categoria.query.filter(db.func.lower(Categoria.nome) == db.func.lower(nome)).first()
        if existente:
            flash(f'A categoria "{nome}" já existe.', "warning")
            return redirect(url_for("categorias.categorias"))
        try:
            db.session.add(Categoria(nome=nome))
            db.session.commit()
            flash(f'Categoria "{nome}" criada com sucesso!', "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao criar categoria: {e}", "danger")
        return redirect(url_for("categorias.categorias"))

    todas = Categoria.query.order_by(Categoria.nome).all()
    produtos_svc.seed_catalog_from_history(db, Produto, ItemGasto)
    produtos = produtos_svc.list_produtos_com_stats(db, Produto, ItemGasto)
    return render_template("categorias.html", categorias=todas, produtos=produtos)


@bp.route("/categorias/editar/<int:id>", methods=["POST"])
@admin_required
def editar_categoria(id: int):
    cat = db.session.get(Categoria, id)
    if not cat:
        flash("Categoria não encontrada.", "danger")
        return redirect(url_for("categorias.categorias"))
    nome_antigo = cat.nome
    nome_novo = request.form.get("nome", "").strip()
    if not nome_novo:
        flash("Nome não pode ser vazio.", "danger")
        return redirect(url_for("categorias.categorias"))
    if nome_antigo.lower() == "outros":
        flash('A categoria "Outros" não pode ser renomeada.', "danger")
        return redirect(url_for("categorias.categorias"))
    dup = Categoria.query.filter(
        db.func.lower(Categoria.nome) == db.func.lower(nome_novo),
        Categoria.id != id,
    ).first()
    if dup:
        flash(f'Já existe uma categoria com o nome "{nome_novo}".', "warning")
        return redirect(url_for("categorias.categorias"))
    try:
        cat.nome = nome_novo
        from models import Conta, ContaReceber, Orcamento

        Conta.query.filter_by(categoria=nome_antigo).update({"categoria": nome_novo})
        ContaReceber.query.filter_by(categoria=nome_antigo).update({"categoria": nome_novo})
        ItemGasto.query.filter_by(categoria=nome_antigo).update({"categoria": nome_novo})
        ListaCompras.query.filter_by(categoria=nome_antigo).update({"categoria": nome_novo})
        Orcamento.query.filter_by(categoria=nome_antigo).update({"categoria": nome_novo})
        db.session.commit()
        flash(
            f'Categoria renomeada de "{nome_antigo}" para "{nome_novo}" e atualizada em todos os registros.',
            "success",
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao renomear: {e}", "danger")
    return redirect(url_for("categorias.categorias"))


@bp.route("/categorias/deletar/<int:id>", methods=["POST"])
@admin_required
def deletar_categoria(id: int):
    cat = db.session.get(Categoria, id)
    if not cat:
        flash("Categoria não encontrada.", "danger")
        return redirect(url_for("categorias.categorias"))
    if cat.nome.lower() == "outros":
        flash('A categoria "Outros" é protegida e não pode ser excluída.', "danger")
        return redirect(url_for("categorias.categorias"))
    nome = cat.nome
    try:
        from models import Conta, ContaReceber, Orcamento

        Conta.query.filter_by(categoria=nome).update({"categoria": "Outros"})
        ContaReceber.query.filter_by(categoria=nome).update({"categoria": "Outros"})
        ItemGasto.query.filter_by(categoria=nome).update({"categoria": "Outros"})
        ListaCompras.query.filter_by(categoria=nome).update({"categoria": "Outros"})
        Orcamento.query.filter_by(categoria=nome).delete()
        db.session.delete(cat)
        db.session.commit()
        flash(f'Categoria "{nome}" excluída. Todos os registros foram movidos para "Outros".', "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir: {e}", "danger")
    return redirect(url_for("categorias.categorias"))


@bp.route("/categorias/produto/salvar/<int:id>", methods=["POST"])
@admin_required
def salvar_produto_catalogo(id: int):
    try:
        produtos_svc.update_produto_catalog(
            db,
            Produto,
            ItemGasto,
            ListaCompras,
            id,
            nome=request.form.get("nome", ""),
            marca=request.form.get("marca", ""),
            unidade=request.form.get("unidade", "un"),
            categoria=request.form.get("categoria", "Outros"),
            aliases_raw=request.form.get("aliases", ""),
        )
        return jsonify({"sucesso": True})
    except ValueError as e:
        return jsonify({"sucesso": False, "erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@bp.route("/categorias/produto/fusao", methods=["POST"])
@admin_required
def fusao_produtos():
    data = request.get_json(silent=True) or {}
    target_id = data.get("target_id")
    source_ids = data.get("source_ids") or []
    if not target_id or len(source_ids) < 1:
        return jsonify({"sucesso": False, "erro": "Selecione ao menos 2 produtos."}), 400
    try:
        produtos_svc.merge_produtos(
            db, Produto, ItemGasto, ListaCompras,
            int(target_id), [int(s) for s in source_ids],
        )
        return jsonify({"sucesso": True})
    except ValueError as e:
        return jsonify({"sucesso": False, "erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@bp.route("/categorias/produto/deletar/<int:id>", methods=["POST"])
@admin_required
def deletar_produto_catalogo(id: int):
    try:
        produtos_svc.delete_produto_catalog(db, Produto, ItemGasto, id)
        return jsonify({"sucesso": True})
    except ValueError as e:
        return jsonify({"sucesso": False, "erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@bp.route("/api/sugerir_produto")
def sugerir_produto():
    nome = request.args.get("nome", "").strip()
    if not nome:
        return jsonify({"categoria": None, "ultimo_preco": None})

    itens = _buscar_sugestoes_produto(nome, limit=1)
    if itens:
        return jsonify(
            {
                "categoria": itens[0]["categoria"],
                "ultimo_preco": itens[0]["ultimo_preco"],
            }
        )
    return jsonify({"categoria": None, "ultimo_preco": None})


@bp.route("/api/sugerir_produtos")
def sugerir_produtos():
    q = request.args.get("q", request.args.get("nome", "")).strip()
    if len(q) < 2:
        return jsonify({"itens": []})
    return jsonify({"itens": _buscar_sugestoes_produto(q, limit=8)})
