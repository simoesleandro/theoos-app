"""Blueprint de autenticação (login/logout)."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models import db
from theoos.auth import pin_configured, verify_pin

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if verify_pin(db, pin):
            session["theoos_auth"] = True
            session["theoos_actor"] = request.form.get("nome", "").strip() or "web"
            flash("Acesso liberado.", "success")
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("PIN incorreto.", "danger")
        return redirect(url_for("auth.login"))
    if session.get("theoos_auth"):
        return redirect(request.args.get("next") or url_for("dashboard.index"))
    return render_template("login.html", pin_enabled=pin_configured(db))


@bp.route("/logout")
def logout():
    session.clear()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("auth.login"))
