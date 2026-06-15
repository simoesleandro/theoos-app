"""Instâncias compartilhadas de extensões Flask (limiter, csrf, etc.).

São criadas não-inicializadas aqui e bindadas em `app.py` via init_app.
Permitem que blueprints importem e usem decoradores sem depender de `app.py`.
"""
from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour", "30 per minute"],
    storage_uri="memory://",
    headers_enabled=True,
)
