"""Auth do ThéoOS: login por usuário/senha + PIN opcional para web na LAN.

Compat: PIN legado continua funcionando (verifica via env WEB_PIN ou
config web_pin_hash). Novo sistema: login com username/password (Usuario model).

Roles:
    admin  - tudo (criar/editar/deletar usuarios, ver logs, gerenciar config)
    viewer - só leitura (dashboards, relatorios, lista de compras)
"""
from __future__ import annotations

import os
import secrets
from functools import wraps

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from models import Usuario, db
from theoos.db_migrate import get_setting, set_setting

auth_bp = Blueprint("auth", __name__)

PUBLIC_ENDPOINTS = {
    "auth.login",
    "auth.logout",
    "static",
    "favicon",
    "health",
    "dashboard.api_dashboard_week",
    "api.api_vencimentos",
    "api.api_insights",
    "dashboard.favicon",
}


def pin_configured(db) -> bool:
    pin_hash = get_setting(db, "web_pin_hash")
    env_pin = os.getenv("WEB_PIN", "").strip()
    return bool(pin_hash or env_pin)


def verify_pin(db, pin: str) -> bool:
    pin = (pin or "").strip()
    if not pin:
        return False
    stored = get_setting(db, "web_pin_hash")
    if stored and check_password_hash(stored, pin):
        return True
    env_pin = os.getenv("WEB_PIN", "").strip()
    return bool(env_pin and pin == env_pin)


def set_pin(db, pin: str) -> None:
    set_setting(db, "web_pin_hash", generate_password_hash(pin.strip()))


def clear_pin(db) -> None:
    from sqlalchemy import text

    with db.engine.connect() as conn:
        conn.execute(text("DELETE FROM app_setting WHERE key='web_pin_hash'"))
        conn.commit()


def verify_user(db, username: str, password: str) -> Usuario | None:
    user = Usuario.query.filter_by(username=(username or "").strip(), ativo=True).first()
    if not user:
        return None
    if not check_password_hash(user.password_hash, password or ""):
        return None
    return user


def create_user(db, username: str, password: str, nome: str = "", role: str = "viewer") -> Usuario:
    u = Usuario(
        username=username.strip(),
        nome=(nome or username).strip(),
        password_hash=generate_password_hash(password),
        role=role,
        ativo=True,
    )
    db.session.add(u)
    db.session.commit()
    return u


def ensure_default_admin(db) -> Usuario | None:
    """Cria um admin inicial se não existir nenhum usuario. Username/senha
    definidos por env (THEOOS_ADMIN_USERNAME / THEOOS_ADMIN_PASSWORD) ou
    gerados aleatoriamente + log warning.
    """
    if Usuario.query.first() is not None:
        return None
    username = os.getenv("THEOOS_ADMIN_USERNAME", "admin")
    password = os.getenv("THEOOS_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    if not os.getenv("THEOOS_ADMIN_PASSWORD"):
        from theoos.logging_setup import get_logger
        get_logger(__name__).warning(
            "Primeiro boot: admin criado com username=%r password=%r "
            "(defina THEOOS_ADMIN_PASSWORD antes de subir em prod).",
            username, password,
        )
    return create_user(db, username, password, nome="Administrador", role="admin")


def current_user() -> Usuario | None:
    uid = session.get("theoos_user_id")
    if not uid:
        return None
    return db.session.get(Usuario, int(uid))


def is_admin() -> bool:
    u = current_user()
    return u is not None and u.role == "admin"


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("theoos_auth"):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("theoos_auth"):
            return redirect(url_for("auth.login", next=request.path))
        if not is_admin():
            from flask import abort
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def init_app(app, db) -> None:
    """Compat shim. Garante admin no primeiro request e injeta contexto."""

    @app.before_request
    def _ensure_admin():
        if not getattr(app, "_theoos_admin_ensured", False):
            try:
                ensure_default_admin(db)
            except Exception:
                pass
            app._theoos_admin_ensured = True

    @app.context_processor
    def auth_context():
        return {
            "current_user_obj": current_user(),
            "current_user_role": session.get("theoos_user_role"),
            "is_admin": is_admin(),
            "pin_enabled": pin_configured(db),
        }
