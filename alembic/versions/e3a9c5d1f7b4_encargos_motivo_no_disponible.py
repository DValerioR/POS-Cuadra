"""encargos: motivo de no se pudo encargar

Revision ID: e3a9c5d1f7b4
Revises: d1f7b3c9e5a2
Create Date: 2026-09-30 16:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3a9c5d1f7b4'
down_revision: Union[str, None] = 'd1f7b3c9e5a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('encargos', sa.Column('motivo_no_disponible', sa.String(), nullable=True))
    op.add_column('encargos', sa.Column('motivo_detalle', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('encargos', 'motivo_detalle')
    op.drop_column('encargos', 'motivo_no_disponible')
