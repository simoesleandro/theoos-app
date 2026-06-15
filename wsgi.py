"""WSGI entrypoint para Waitress (produção) e servidor de dev.

Em produção (WinSW ou systemd):
    waitress-serve --port=5000 wsgi:application

Em dev:
    python wsgi.py
"""
from __future__ import annotations

import os

from app import app

application = app


def main() -> None:
    port = int(os.getenv("PORT", "5000"))
    as_service = os.getenv("THEOOS_SERVICE", "").strip().lower() in ("1", "true", "yes")
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true") and not as_service

    if as_service:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=4, ident="ThéoOS")
    else:
        app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=debug)


if __name__ == "__main__":
    main()
