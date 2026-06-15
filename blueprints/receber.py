"""Blueprint de contas a receber."""
from __future__ import annotations

import calendar
import os
from datetime import date, datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from models import ContaReceber, Financas, ItemGasto, db

bp = Blueprint("receber", __name__)


def _current_actor() -> str:
    from flask import session

    return session.get("theoos_actor") or "web"


@bp.route("/receber", methods=["GET", "POST"])
def receber():
    if request.method == "POST":
        nome = request.form["nome"]
        valor = float(request.form["valor"].replace(",", "."))
        data_obj = datetime.strptime(request.form["data_esperada"], "%Y-%m-%d").date()
        categoria = request.form["categoria"]

        foto_path = None
        if "foto" in request.files:
            arquivo = request.files["foto"]
            if arquivo.filename:
                filename = secure_filename(
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_rec_{arquivo.filename}"
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
                data_esp = date(year, month, day)
                db.session.add(
                    ContaReceber(
                        nome=nome,
                        valor=valor,
                        data_esperada=data_esp,
                        foto_path=foto_path,
                        categoria=categoria,
                    )
                )
            db.session.commit()
            flash(
                f"Recebível e seus {meses} meses recorrentes cadastrados com sucesso!",
                "success",
            )
        else:
            db.session.add(
                ContaReceber(
                    nome=nome,
                    valor=valor,
                    data_esperada=data_obj,
                    foto_path=foto_path,
                    categoria=categoria,
                )
            )
            db.session.commit()
            flash("Recebível cadastrado com sucesso!", "success")
        return redirect(url_for("receber.receber"))

    pendentes = (
        ContaReceber.query.filter_by(status="pendente")
        .order_by(ContaReceber.data_esperada)
        .all()
    )
    recebidos = (
        ContaReceber.query.filter_by(status="recebido")
        .order_by(ContaReceber.data_esperada.desc())
        .limit(30)
        .all()
    )
    hoje = datetime.now().date()
    return render_template(
        "receber.html",
        contas=pendentes,
        contas_recebidas=recebidos,
        hoje=hoje,
        today_date=hoje,
        today_str=hoje.strftime("%Y-%m-%d"),
    )


@bp.route("/receber/editar/<int:id>", methods=["POST"])
def editar_recebivel(id: int):
    recebivel = db.session.get(ContaReceber, id)
    if not recebivel:
        flash("Recebível não encontrado.", "danger")
        return redirect(url_for("receber.receber"))

    try:
        nome = request.form["nome"]
        valor = float(request.form["valor"].replace(",", "."))
        data_obj = datetime.strptime(request.form["data_esperada"], "%Y-%m-%d").date()
        categoria = request.form["categoria"]

        if "foto" in request.files:
            arquivo = request.files["foto"]
            if arquivo.filename:
                if recebivel.foto_path:
                    antigo = os.path.join(
                        current_app.config["UPLOAD_FOLDER"], recebivel.foto_path
                    )
                    if os.path.exists(antigo):
                        try:
                            os.remove(antigo)
                        except Exception:
                            pass
                filename = secure_filename(
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_rec_{arquivo.filename}"
                )
                arquivo.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                recebivel.foto_path = filename

        if request.form.get("remover_foto") == "true":
            if recebivel.foto_path:
                antigo = os.path.join(current_app.config["UPLOAD_FOLDER"], recebivel.foto_path)
                if os.path.exists(antigo):
                    try:
                        os.remove(antigo)
                    except Exception:
                        pass
                recebivel.foto_path = None

        recebivel.nome = nome
        recebivel.valor = valor
        recebivel.data_esperada = data_obj
        recebivel.categoria = categoria

        db.session.commit()
        flash("Recebível atualizado com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao atualizar recebível: {e}", "danger")

    return redirect(url_for("receber.receber"))


@bp.route("/receber/deletar/<int:id>", methods=["POST"])
def deletar_recebivel(id: int):
    recebivel = db.session.get(ContaReceber, id)
    if recebivel:
        if recebivel.foto_path:
            caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], recebivel.foto_path)
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except Exception:
                    pass
        db.session.delete(recebivel)
        db.session.commit()
        flash("Recebível excluído com sucesso!", "success")
    else:
        flash("Recebível não encontrado.", "danger")
    return redirect(url_for("receber.receber"))


@bp.route("/receber/dar_baixa/<int:id>", methods=["POST"])
def dar_baixa_recebivel(id: int):
    recebivel = db.session.get(ContaReceber, id)
    if recebivel:
        recebivel.status = "recebido"
        novo_credito = Financas(
            valor=recebivel.valor,
            descricao=f"Recebimento: {recebivel.nome}",
            foto_path=recebivel.foto_path,
            tipo="credito",
        )
        db.session.add(novo_credito)
        db.session.flush()
        db.session.add(
            ItemGasto(
                financa_id=novo_credito.id,
                nome=recebivel.nome,
                quantidade=1.0,
                valor_unitario=recebivel.valor,
                valor_total=recebivel.valor,
                categoria=recebivel.categoria,
            )
        )
        db.session.commit()
        flash(f'Recebível "{recebivel.nome}" recebido com sucesso!', "success")
    return redirect(url_for("receber.receber"))
