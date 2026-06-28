"""baseline schema v7

Baseline: marca o schema atual do ThéoOS (v7) como ponto de partida do Alembic.
Não cria/aplica nenhuma mudança — apenas registra o estado atual.

Para usar:
    alembic stamp head

Para gerar uma nova migration após mudar models.py:
    alembic revision --autogenerate -m "descrição da mudança"
    alembic upgrade head

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-28 18:48:00.000000
"""
from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Baseline — sem mudanças. O schema v7 já está aplicado via db_migrate.py."""
    pass


def downgrade() -> None:
    """Baseline — não há o que reverter."""
    pass
