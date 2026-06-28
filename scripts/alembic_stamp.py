"""Alembic helper — stamp inicial do ThéoOS.

Após instalar Alembic, rodar uma única vez para marcar o schema v7
existente como já migrado:
    python scripts/alembic_stamp.py

Daí em diante, qualquer mudança em models.py pode virar uma migration:
    alembic revision --autogenerate -m "msg"
    alembic upgrade head
"""
from __future__ import annotations

import os
import sys

# Permite rodar este script a partir de qualquer CWD
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


def main() -> None:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    print("[ThéOS] Marcando schema atual como v7 (baseline)...")
    with app.app_context():
        command.stamp(cfg, "head")
    print("[ThéOS] OK. Schema marcado. Próximas mudanças em models.py:")
    print("    alembic revision --autogenerate -m 'descrição'")
    print("    alembic upgrade head")


if __name__ == "__main__":
    main()
