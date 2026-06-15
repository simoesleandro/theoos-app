"""Blueprint da lista de compras e baixa por cupom."""
from __future__ import annotations
from theoos.auth import admin_required

import os
from collections import defaultdict
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from models import Financas, ItemGasto, ListaCompras, db
from theoos import insights, telegram_lista

bp = Blueprint("lista", __name__)


def _current_actor() -> str:
    from flask import session

    return session.get("theoos_actor") or "web"


@bp.route("/lista")
def lista_compras():
    itens_pendentes = ListaCompras.query.filter_by(status="pendente").all()
    itens_comprados = (
        ListaCompras.query.filter_by(status="comprado")
        .order_by(ListaCompras.id.desc())
        .limit(20)
        .all()
    )

    total_estimado = 0.0
    for item in itens_pendentes:
        query = ItemGasto.query.filter(
            db.or_(
                db.func.lower(ItemGasto.nome) == db.func.lower(item.item.strip()),
                db.func.lower(ItemGasto.nome_normalizado) == db.func.lower(item.item.strip()),
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

    nome_item_expr = db.case(
        (db.and_(ItemGasto.nome_normalizado != None, ItemGasto.nome_normalizado != ""), ItemGasto.nome_normalizado),
        else_=ItemGasto.nome,
    )
    subquery = (
        db.session.query(
            nome_item_expr.label("nome_item"),
            ItemGasto.marca,
            ItemGasto.unidade,
            ItemGasto.categoria,
            db.func.max(ItemGasto.id).label("max_id"),
        )
        .group_by(nome_item_expr, ItemGasto.marca, ItemGasto.unidade, ItemGasto.categoria)
        .subquery()
    )

    itens_gasto = (
        db.session.query(
            subquery.c.nome_item,
            subquery.c.marca,
            subquery.c.unidade,
            subquery.c.categoria,
            ItemGasto.valor_unitario,
        )
        .join(ItemGasto, ItemGasto.id == subquery.c.max_id)
        .all()
    )

    itens_lista = (
        db.session.query(
            ListaCompras.item.label("nome_item"),
            ListaCompras.marca,
            ListaCompras.unidade,
            ListaCompras.categoria,
        )
        .group_by(ListaCompras.item, ListaCompras.marca, ListaCompras.unidade, ListaCompras.categoria)
        .all()
    )

    produtos_set: set = set()
    produtos_historico: list[dict] = []

    for p in itens_gasto:
        key = (
            p.nome_item.strip().lower(),
            (p.marca or "").strip().lower(),
            p.unidade.strip().lower(),
            p.categoria.strip().lower(),
        )
        if key not in produtos_set:
            produtos_set.add(key)
            produtos_historico.append(
                {
                    "nome_item": p.nome_item.strip(),
                    "marca": p.marca.strip() if p.marca else None,
                    "unidade": p.unidade.strip() or "un",
                    "categoria": p.categoria.strip() or "Supermercado",
                    "ultimo_preco": p.valor_unitario,
                }
            )

    for p in itens_lista:
        key = (
            p.nome_item.strip().lower(),
            (p.marca or "").strip().lower(),
            p.unidade.strip().lower(),
            p.categoria.strip().lower(),
        )
        if key not in produtos_set:
            produtos_set.add(key)
            produtos_historico.append(
                {
                    "nome_item": p.nome_item.strip(),
                    "marca": p.marca.strip() if p.marca else None,
                    "unidade": p.unidade.strip() or "un",
                    "categoria": p.categoria.strip() or "Supermercado",
                    "ultimo_preco": None,
                }
            )

    cesta_lojas = insights.basket_estimates_by_store(db, ListaCompras, ItemGasto, Financas)

    return render_template(
        "lista.html",
        itens_pendentes=itens_pendentes,
        itens_comprados=itens_comprados,
        total_estimado=total_estimado,
        produtos_historico=produtos_historico,
        cesta_lojas=cesta_lojas,
    )


@bp.route("/comprado/<int:id>", methods=["POST"])
@admin_required
def marcar_comprado(id: int):
    qtd_comprada = float(request.args.get("qtd", 0))
    valor_pago = float(request.args.get("preco", "0").replace(",", "."))

    item = db.session.get(ListaCompras, id)
    if item:
        if qtd_comprada >= item.quantidade:
            item.status = "comprado"
            item.marcado = False
        else:
            item.quantidade -= qtd_comprada

        novo_gasto = Financas(
            valor=valor_pago,
            descricao=f"Compra: {item.item}",
            criado_por=_current_actor(),
        )
        db.session.add(novo_gasto)
        db.session.flush()

        valor_unitario = valor_pago / qtd_comprada if qtd_comprada > 0 else 0.0
        db.session.add(
            ItemGasto(
                financa_id=novo_gasto.id,
                nome=item.item,
                quantidade=qtd_comprada,
                valor_unitario=valor_unitario,
                valor_total=valor_pago,
                categoria=item.categoria,
                marca=item.marca,
                unidade=item.unidade,
                mercado=request.args.get("mercado", "").strip() or None,
            )
        )
        db.session.commit()

    return redirect(url_for("lista.lista_compras"))


@bp.route("/lista/add", methods=["POST"])
@admin_required
def lista_add():
    item = request.form.get("item", "").strip()
    if not item:
        return redirect(url_for("lista.lista_compras"))
    try:
        quantidade = float(request.form.get("quantidade", "1").replace(",", "."))
    except ValueError:
        quantidade = 1.0
    unidade = request.form.get("unidade", "un").strip() or "un"
    categoria = request.form.get("categoria", "Outros")
    marca = request.form.get("marca", "").strip() or None
    db.session.add(
        ListaCompras(
            item=item,
            quantidade=quantidade,
            unidade=unidade,
            categoria=categoria,
            marca=marca,
            status="pendente",
            criado_por=_current_actor(),
        )
    )
    db.session.commit()
    flash(f'"{item}" adicionado à lista!', "success")
    return redirect(url_for("lista.lista_compras"))


@bp.route("/lista/add_from_history")
@admin_required
def add_from_history():
    item = request.args.get("item", "").strip()
    marca = request.args.get("marca", "").strip() or None
    unidade = request.args.get("unidade", "un").strip() or "un"
    categoria = request.args.get("categoria", "Supermercado").strip()

    if item:
        existente = ListaCompras.query.filter_by(item=item, marca=marca, status="pendente").first()
        if existente:
            existente.quantidade += 1.0
        else:
            db.session.add(
                ListaCompras(
                    item=item,
                    marca=marca,
                    quantidade=1.0,
                    unidade=unidade,
                    categoria=categoria,
                    status="pendente",
                )
            )
        db.session.commit()
        flash(f'"{item}" adicionado à lista!', "success")
    return redirect(url_for("lista.lista_compras"))


@bp.route("/lista/delete/<int:id>", methods=["POST"])
@admin_required
def lista_delete(id: int):
    item = db.session.get(ListaCompras, id)
    if item:
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for("lista.lista_compras"))


@bp.route("/lista/limpar", methods=["POST"])
@admin_required
def lista_limpar():
    ListaCompras.query.filter_by(status="comprado").delete()
    db.session.commit()
    flash("Itens concluídos removidos.", "success")
    return redirect(url_for("lista.lista_compras"))


@bp.route("/lista/editar/<int:id>", methods=["POST"])
@admin_required
def lista_editar(id: int):
    item_obj = db.session.get(ListaCompras, id)
    if item_obj:
        item = request.form.get("item", "").strip()
        if not item:
            flash("O nome do item não pode ser vazio.", "danger")
            return redirect(url_for("lista.lista_compras"))
        try:
            quantidade = float(request.form.get("quantidade", "1").replace(",", "."))
        except ValueError:
            quantidade = 1.0
        unidade = request.form.get("unidade", "un").strip() or "un"
        categoria = request.form.get("categoria", "Outros")
        marca = request.form.get("marca", "").strip() or None

        item_obj.item = item
        item_obj.quantidade = quantidade
        item_obj.unidade = unidade
        item_obj.categoria = categoria
        item_obj.marca = marca
        db.session.commit()
        flash(f'"{item}" atualizado com sucesso!', "success")
    else:
        flash("Item não encontrado.", "danger")
    return redirect(url_for("lista.lista_compras"))


@bp.route("/lista/enviar_telegram")
def lista_enviar_telegram():
    itens_pendentes = (
        ListaCompras.query.filter_by(status="pendente")
        .order_by(ListaCompras.categoria, ListaCompras.item)
        .all()
    )
    if not itens_pendentes:
        flash("Nenhum item pendente na lista de compras.", "warning")
        return redirect(url_for("lista.lista_compras"))

    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        flash("Configurações do Telegram ausentes no servidor.", "danger")
        return redirect(url_for("lista.lista_compras"))

    total_estimado = telegram_lista.calc_total_estimado(itens_pendentes, ItemGasto, db)

    try:
        import telebot

        bot = telebot.TeleBot(token)
        telegram_lista.send_lista_message(bot, chat_id, itens_pendentes, total_estimado=total_estimado)
        flash("Lista de compras enviada com sucesso para o Telegram!", "success")
    except Exception as e:
        flash(f"Erro ao enviar mensagem via robô: {e}", "danger")

    return redirect(url_for("lista.lista_compras"))


@bp.route("/lista/baixar_txt")
def lista_baixar_txt():
    itens_pendentes = ListaCompras.query.filter_by(status="pendente").all()

    txt = "LISTA DE COMPRAS FAMÍLIA\n"
    txt += f"Gerada em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}\n"
    txt += "=" * 40 + "\n\n"

    if not itens_pendentes:
        txt += "Nenhum item pendente na lista.\n"
    else:
        por_categoria: dict[str, list] = defaultdict(list)
        for it in itens_pendentes:
            por_categoria[it.categoria].append(it)

        for cat, items in por_categoria.items():
            txt += f"[{cat.upper()}]\n"
            for it in items:
                qty_val = it.quantidade
                if qty_val == int(qty_val):
                    qty_str = str(int(qty_val))
                else:
                    qty_str = f"{qty_val:.1f}".replace(".", ",")
                txt += f"[ ] {it.item} - {qty_str} {it.unidade}\n"
            txt += "\n"

    txt += "=" * 40 + "\n"
    txt += f"Total: {len(itens_pendentes)} itens pendentes.\n"

    response = make_response(txt)
    response.headers["Content-Disposition"] = (
        f"attachment; filename=lista_de_compras_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    )
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response
