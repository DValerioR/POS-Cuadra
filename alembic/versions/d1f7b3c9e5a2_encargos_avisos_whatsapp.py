"""encargos: no disponible y avisos por whatsapp

Revision ID: d1f7b3c9e5a2
Revises: c9e5a3b7d2f1
Create Date: 2026-09-30 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1f7b3c9e5a2'
down_revision: Union[str, None] = 'c9e5a3b7d2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Un valor nuevo de un ENUM no se puede usar en la misma transacción: va aparte.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE estadoencargo ADD VALUE IF NOT EXISTS 'NO_DISPONIBLE'")
    op.add_column('encargos', sa.Column('avisado_por', sa.String(), nullable=True))
    op.add_column('encargos', sa.Column('aviso_texto', sa.String(), nullable=True))
    op.add_column('encargos', sa.Column('aviso_error', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('encargos', 'aviso_error')
    op.drop_column('encargos', 'aviso_texto')
    op.drop_column('encargos', 'avisado_por')
    # (PostgreSQL no permite quitar un valor de un ENUM; se queda.)
