"""entradas solo historial

Revision ID: b8d4f2a6c1e3
Revises: a7c3e9f1b2d4
Create Date: 2026-09-30 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d4f2a6c1e3'
down_revision: Union[str, None] = 'a7c3e9f1b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('entradas', sa.Column('afecta_inventario', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.alter_column('entrada_renglones', 'lote_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column('entrada_renglones', 'lote_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('entradas', 'afecta_inventario')
