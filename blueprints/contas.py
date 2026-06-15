"""Blueprint de contas a pagar."""
from __future__ import annotations

import calendar
import os
from datetime import date, datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import or_

from models import Conta, Financas, ItemGasto, db

bp = Blueprint("contas", __name__)


def _current_actor() -> str:
    from flask import session

    return session.get("theoos_actor") or "web"


@bp.route("/contas", methods=["GET", "POST"])
def contas():
    if request.method == "POST":
        nome = request.form["nome"]
        valor = float(request.form["valor"].replace(",", "."))
        data_obj = datetime.strptime(request.form["data_vencimento"], "%Y-%m-%d").date()
        categoria = request.form["categoria"]

        foto_path = None
        if "foto" in request.files:
            arquivo = request.files["foto"]
            if arquivo.filename:
                from werkzeug.utils import secure_filename

                filename = secure_filename(
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{arquivo.filename}"
                )
                arquivo.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                foto_path = filename

        recorrente = "recorrente" in request.form
        meses = int(request.form.get("meses", 1)) if recorrente else 1
        if meses < 1:
            meses = 1

        if meses > 1:
            for i in range(meses):
                new_month = data_obj.month - 1 + i
                year = data_obj.year + new_month // 12
                month = new_month % 12 + 1
                day = min(data_obj.day, calendar.monthrange(year, month)[1])
                data_venc = date(year, month, day)
                db.session.add(
                    Conta(
                        nome=nome,
                        valor=valor,
                        data_vencimento=data_venc,
                        foto_path=foto_path,
                        categoria=categoria,
                    )
                )
            db.session.commit()
            flash(f"Conta e suas {meses} parcelas recorrentes cadastradas com sucesso!", "success")
        else:
            db.session.add(
                Conta(
                    nome=nome,
                    valor=valor,
                    data_vencimento=data_obj,
                    foto_path=foto_path,
                    categoria=categoria,
                )
            )
            db.session.commit()
            flash("Conta cadastrada com sucesso!", "success")
        return redirect(url_for("contas.contas"))

    busca_contas = request.args.get("busca_contas", "").strip()
    pag_contas = request.args.get("pag_contas", 1, type=int)

    query_pendentes = Conta.query.filter_by(status="pendente")
    if busca_contas:
        query_pendentes = query_pendentes.filter(Conta.nome.ilike(f"%{busca_contas}%"))
    query_pendentes = query_pendentes.order_by(Conta.data_vencimento)

    soma_filtrada = db.session.query(db.func.sum(Conta.valor)).filter(Conta.status == "pendente")
    if busca_contas:
        soma_filtrada = soma_filtrada.filter(Conta.nome.ilike(f"%{busca_contas}%"))
    soma_filtrada = soma_filtrada.scalar() or 0.0

    paginacao_contas = query_pendentes.paginate(page=pag_contas, per_page=30, error_out=False)

    pagas = (
        Conta.query.filter_by(status="pago")
        .order_by(Conta.data_vencimento.desc())
        .limit(30)
        .all()
    )
    hoje = datetime.now().date()
    return render_template(
        "contas.html",
        contas=paginacao_contas.items,
        paginacao_contas=paginacao_contas,
        busca_contas=busca_contas,
        soma_filtrada=soma_filtrada,
        contas_pagas=pagas,
        hoje=hoje,
        today_date=hoje,
        today_str=hoje.strftime("%Y-%m-%d"),
    )


@bp.route("/contas/editar/<int:id>", methods=["POST"])
def editar_conta(id: int):
    conta = db.session.get(Conta, id)
    if not conta:
        flash("Conta não encontrada.", "danger")
        return redirect(url_for("contas.contas"))

    try:
        nome = request.form["nome"]
        valor = float(request.form["valor"].replace(",", "."))
        data_obj = datetime.strptime(request.form["data_vencimento"], "%Y-%m-%d").date()
        categoria = request.form["categoria"]

        if "foto" in request.files:
            arquivo = request.files["foto"]
            if arquivo.filename:
                from werkzeug.utils import secure_filename

                if conta.foto_path:
                    antigo = os.path.join(current_app.config["UPLOAD_FOLDER"], conta.foto_path)
                    if os.path.exists(antigo):
                        try:
                            os.remove(antigo)
                        except Exception:
                            pass
                filename = secure_filename(
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{arquivo.filename}"
                )
                arquivo.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                conta.foto_path = filename

        if request.form.get("remover_foto") == "true":
            if conta.foto_path:
                antigo = os.path.join(current_app.config["UPLOAD_FOLDER"], conta.foto_path)
                if os.path.exists(antigo):
                    try:
                        os.remove(antigo)
                    except Exception:
                        pass
                conta.foto_path = None

        conta.nome = nome
        conta.valor = valor
        conta.data_vencimento = data_obj
        conta.categoria = categoria

        db.session.commit()
        flash("Conta atualizada com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao atualizar conta: {e}", "danger")

    return redirect(url_for("contas.contas"))


@bp.route("/contas/deletar/<int:id>", methods=["POST"])
def deletar_conta(id: int):
    conta = db.session.get(Conta, id)
    if conta:
        if conta.foto_path:
            caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], conta.foto_path)
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except Exception:
                    pass
        db.session.delete(conta)
        db.session.commit()
        flash("Conta excluída com sucesso!", "success")
    else:
        flash("Conta não encontrada.", "danger")
    return redirect(url_for("contas.contas"))


@bp.route("/pagar_conta/<int:id>", methods=["POST"])
def pagar_conta(id: int):
    conta = db.session.get(Conta, id)
    if conta:
        conta.status = "pago"
        novo_gasto = Financas(
            valor=conta.valor,
            descricao=f"Conta Paga: {conta.nome}",
            foto_path=conta.foto_path,
        )
        db.session.add(novo_gasto)
        db.session.flush()
        db.session.add(
            ItemGasto(
                financa_id=novo_gasto.id,
                nome=conta.nome,
                quantidade=1.0,
                valor_unitario=conta.valor,
                valor_total=conta.valor,
                categoria=conta.categoria,
            )
        )
        db.session.commit()
        flash(f'Conta "{conta.nome}" paga com sucesso!', "success")
    return redirect(url_for("contas.contas"))


@bp.route("/api/contas/bulk_actions", methods=["POST"])
def bulk_actions_contas():
    dados = request.get_json() or {}
    action = dados.get("action", "").strip()
    ids = dados.get("ids", [])
    categoria_nova = dados.get("categoria", "Outros")

    if not ids or action not in ("delete", "pay", "category"):
        return jsonify({"sucesso": False, "erro": "Parâmetros inválidos."}), 400

    try:
        contas_selecionadas = Conta.query.filter(
            Conta.id.in_(ids), Conta.status == "pendente"
        ).all()

        if action == "delete":
            for c in contas_selecionadas:
                if c.foto_path:
                    caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], c.foto_path)
                    if os.path.exists(caminho):
                        try:
                            os.remove(caminho)
                        except Exception:
                            pass
                db.session.delete(c)
            db.session.commit()
            return jsonify(
                {"sucesso": True, "mensagem": f"{len(contas_selecionadas)} conta(s) excluída(s)."}
            )

        elif action == "pay":
            for c in contas_selecionadas:
                c.status = "pago"
                novo_gasto = Financas(
                    valor=c.valor,
                    descricao=f"Conta Paga: {c.nome}",
                    foto_path=c.foto_path,
                    tipo="debito",
                )
                db.session.add(novo_gasto)
                db.session.flush()
                db.session.add(
                    ItemGasto(
                        financa_id=novo_gasto.id,
                        nome=c.nome,
                        quantidade=1.0,
                        valor_unitario=c.valor,
                        valor_total=c.valor,
                        categoria=c.categoria,
                    )
                )
            db.session.commit()
            return jsonify(
                {
                    "sucesso": True,
                    "mensagem": f"{len(contas_selecionadas)} conta(s) marcada(s) como paga(s).",
                }
            )

        elif action == "category":
            for c in contas_selecionadas:
                c.categoria = categoria_nova
            db.session.commit()
            return jsonify(
                {
                    "sucesso": True,
                    "mensagem": f'Categoria alterada para "{categoria_nova}" em {len(contas_selecionadas)} conta(s).',
                }
            )

    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": f"Erro: {e}"}), 500

    return jsonify({"sucesso": False, "erro": "Ação não implementada."}), 500
