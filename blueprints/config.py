"""Blueprint de configurações, backup, importação de extrato e health."""
from __future__ import annotations

import csv
import io
import os
import zipfile
from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from models import Financas, ItemGasto, db
from theoos import audit, backup, reconcile, recurring
from theoos.db_migrate import get_setting, set_setting

bp = Blueprint("config", __name__)


def _actor() -> str:
    from flask import session

    return session.get("theoos_actor") or "web"


@bp.route("/health")
def health():
    return jsonify({"ok": True, "app": "ThéoOS"})


@bp.route("/config", methods=["GET", "POST"])
def config_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "set_pin":
            p1 = request.form.get("pin", "").strip()
            p2 = request.form.get("pin_confirm", "").strip()
            if len(p1) < 4:
                flash("PIN deve ter pelo menos 4 caracteres.", "warning")
            elif p1 != p2:
                flash("PINs não conferem.", "danger")
            else:
                from theoos.auth import set_pin

                set_pin(db, p1)
                flash("PIN configurado.", "success")
        elif action == "clear_pin":
            from theoos.auth import clear_pin

            clear_pin(db)
            flash("PIN removido — painel aberto na rede local.", "info")
        elif action == "reminders":
            days = request.form.get("reminder_days", "2")
            set_setting(db, "reminder_days", days)
            flash("Lembretes atualizados.", "success")
        elif action == "theme":
            theme = request.form.get("theme", "dark")
            set_setting(db, "theme", theme)
            flash("Tema salvo.", "success")
        elif action == "web_notify":
            on = "1" if request.form.get("web_notify") == "on" else "0"
            set_setting(db, "web_notify", on)
            flash("Notificações no navegador atualizadas.", "success")
        elif action == "recurring_add":
            recurring.add_template(
                db,
                request.form.get("nome", "").strip(),
                float(request.form.get("valor", "0").replace(",", ".")),
                request.form.get("categoria", "Outros"),
                int(request.form.get("dia", 1)),
                request.form.get("tipo", "pagar"),
            )
            flash("Conta fixa cadastrada.", "success")
        elif action == "recurring_run":
            from models import Conta, ContaReceber

            n = recurring.run_monthly_generation(db, Conta, ContaReceber)
            flash(f"{n} lançamento(s) gerado(s) para este mês.", "success")
        return redirect(url_for("config.config_page"))

    reminder_days = get_setting(db, "reminder_days", "0,1,2,3,7")
    theme = get_setting(db, "theme", "dark")
    web_notify = get_setting(db, "web_notify", "1") == "1"
    templates = recurring.list_templates(db)
    logs = audit.recent_logs(db, 20)
    return render_template(
        "config.html",
        pin_enabled=False,
        reminder_days=reminder_days,
        theme=theme,
        web_notify=web_notify,
        recurring_templates=templates,
        audit_logs=logs,
        actor=_actor(),
    )


@bp.route("/config/backup")
def config_backup():
    buf = backup.create_backup_zip(current_app)
    fname = f"theoos-backup-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=fname,
    )


@bp.route("/config/restore", methods=["POST"])
def config_restore():
    f = request.files.get("backup")
    if not f:
        flash("Selecione um arquivo .zip de backup.", "danger")
        return redirect(url_for("config.config_page"))
    try:
        backup.restore_from_zip(current_app, f.read())
        flash("Backup restaurado. Reinicie o serviço se necessário.", "success")
    except Exception as e:
        flash(f"Erro ao restaurar: {e}", "danger")
    return redirect(url_for("config.config_page"))


@bp.route("/exportar/fluxo_caixa")
def exportar_fluxo_caixa():
    hoje = date.today()
    rows = []
    for m in range(12):
        month = hoje.month - m
        year = hoje.year
        while month < 1:
            month += 12
            year -= 1
        primeiro = datetime(year, month, 1)
        if month == 12:
            ultimo = datetime(year, 12, 31, 23, 59, 59)
        else:
            ultimo = datetime(year, month + 1, 1) - timedelta(seconds=1)
        deb = (
            db.session.query(db.func.sum(Financas.valor))
            .filter(
                Financas.tipo == "debito",
                Financas.data >= primeiro,
                Financas.data <= ultimo,
            )
            .scalar()
            or 0
        )
        cred = (
            db.session.query(db.func.sum(Financas.valor))
            .filter(
                Financas.tipo == "credito",
                Financas.data >= primeiro,
                Financas.data <= ultimo,
            )
            .scalar()
            or 0
        )
        rows.append((f"{month:02d}/{year}", deb, cred, cred - deb))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Mes", "Despesas", "Receitas", "Saldo"])
    w.writerows(reversed(rows))
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=fluxo_caixa.csv"
    return resp


@bp.route("/importar/cartao", methods=["GET", "POST"])
def importar_cartao():
    if request.method == "GET":
        return render_template(
            "importar_cartao.html",
            lancamentos=None,
            meta=None,
            importados=0,
        )
    f = request.files.get("csv")
    if not f:
        flash("Envie um arquivo CSV.", "danger")
        return redirect(url_for("config.importar_cartao"))
    try:
        lancamentos, meta = reconcile.parse_bank_csv(f.read())
    except Exception as e:
        flash(f"Erro ao processar CSV: {e}", "danger")
        return redirect(url_for("config.importar_cartao"))
    matched = reconcile.match_against_financas(lancamentos, Financas)
    novos = [x for x in matched if x.get("novo")]
    for lan in novos[:200]:
        eh_saida = lan.get("_eh_saida", True)
        db.session.add(
            Financas(
                valor=lan["valor"],
                descricao=f"CSV: {lan['descricao'][:80]}",
                tipo="debito" if eh_saida else "credito",
                data=datetime.strptime(lan["data"], "%Y-%m-%d"),
                criado_por=_actor(),
            )
        )
    db.session.commit()
    flash(
        f"{meta['validos']} linhas válidas detectadas ({meta['formato']}) — "
        f"{len(novos)} novos lançamentos importados.",
        "success",
    )
    return render_template(
        "importar_cartao.html",
        lancamentos=matched,
        meta=meta,
        importados=len(novos),
    )
