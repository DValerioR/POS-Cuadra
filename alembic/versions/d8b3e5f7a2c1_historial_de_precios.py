"""historial de precios

Revision ID: d8b3e5f7a2c1
Revises: c4f2a8d1e9b3
Create Date: 2026-09-29 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd8b3e5f7a2c1'
down_revision: Union[str, None] = 'c4f2a8d1e9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('precios_historial',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('producto_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('precio_anterior', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('precio_nuevo', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('origen', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_precios_historial_negocio_id'), 'precios_historial', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_precios_historial_producto_id'), 'precios_historial', ['producto_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_precios_historial_producto_id'), table_name='precios_historial')
    op.drop_index(op.f('ix_precios_historial_negocio_id'), table_name='precios_historial')
    op.drop_table('precios_historial')
