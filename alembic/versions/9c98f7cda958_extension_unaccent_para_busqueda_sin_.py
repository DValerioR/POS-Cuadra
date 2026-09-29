"""extension unaccent para busqueda sin acentos

Revision ID: 9c98f7cda958
Revises: 27f89bf866b7
Create Date: 2026-09-28 21:52:28.332469

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9c98f7cda958'
down_revision: Union[str, None] = '27f89bf866b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Para buscar productos sin importar acentos ("acido" encuentra "ÁCIDO").
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS unaccent")
