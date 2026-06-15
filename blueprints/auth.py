"""Blueprint de autenticação (login/logout)."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models import db
from theoos.auth import (
    create_user,
    current_user,
    pin_configured,
    verify_pin,
    verify_user,
)
from theoos.extensions import limiter

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 100 per hour")
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = verify_user(db, username, password)
        if user:
            session["theoos_auth"] = True
            session["theoos_user_id"] = user.id
            session["theoos_user_role"] = user.role
            session["theoos_actor"] = user.username
            flash(f"Bem-vindo, {user.nome or user.username}!", "success")
            return redirect(request.args.get("next") or url_for("dashboard.index"))

        pin = request.form.get("pin", "")
        if pin and verify_pin(db, pin):
            session["theoos_auth"] = True
            session["theoos_user_role"] = "admin"
            session["theoos_actor"] = "pin"
            flash("Acesso via PIN.", "success")
            return redirect(request.args.get("next") or url_for("dashboard.index"))

        flash("Usuário/senha ou PIN inválido.", "danger")
        return redirect(url_for("auth.login"))

    if session.get("theoos_auth"):
        return redirect(request.args.get("next") or url_for("dashboard.index"))
    return render_template("login.html", pin_enabled=pin_configured(db))


@bp.route("/logout")
def logout():
    session.clear()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("auth.login"))
