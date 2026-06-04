"""PIN simples para proteger o painel web na rede local."""
import os
from functools import wraps

from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from theoos.db_migrate import get_setting, set_setting

PUBLIC_ENDPOINTS = {
    "login",
    "logout",
    "static",
    "health",
}


def pin_configured(db):
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


def set_pin(db, pin: str):
    set_setting(db, "web_pin_hash", generate_password_hash(pin.strip()))


def clear_pin(db):
    from sqlalchemy import text

    with db.engine.connect() as conn:
        conn.execute(text("DELETE FROM app_setting WHERE key='web_pin_hash'"))
        conn.commit()


def init_app(app, db):
    @app.before_request
    def require_auth():
        if request.endpoint in PUBLIC_ENDPOINTS or (
            request.endpoint and request.endpoint.startswith("static")
        ):
            return None
        if not pin_configured(db):
            return None
        if session.get("theoos_auth"):
            return None
        return redirect(url_for("login", next=request.path))

    @app.context_processor
    def auth_context():
        return {"pin_enabled": pin_configured(db)}


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("theoos_auth"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapped
