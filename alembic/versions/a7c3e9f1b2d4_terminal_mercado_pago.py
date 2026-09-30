"""terminal mercado pago

Revision ID: a7c3e9f1b2d4
Revises: f1a2b3c4d5e6
Create Date: 2026-09-30 13:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c3e9f1b2d4'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cajas', sa.Column('terminal_mp', sa.String(), nullable=True))
    op.create_table('cobros_terminal',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('caja_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('terminal_id', sa.String(), nullable=False),
    sa.Column('monto', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('idempotencia', sa.String(), nullable=False),
    sa.Column('orden_id', sa.String(), nullable=True),
    sa.Column('pago_id', sa.String(), nullable=True),
    sa.Column('estado', sa.String(), nullable=False),
    sa.Column('detalle', sa.String(), nullable=True),
    sa.Column('tarjeta', sa.String(), nullable=True),
    sa.Column('venta_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['caja_id'], ['cajas.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cobros_terminal_negocio_id'), 'cobros_terminal', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_cobros_terminal_caja_id'), 'cobros_terminal', ['caja_id'], unique=False)
    op.create_index(op.f('ix_cobros_terminal_orden_id'), 'cobros_terminal', ['orden_id'], unique=False)
    op.create_index(op.f('ix_cobros_terminal_venta_id'), 'cobros_terminal', ['venta_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cobros_terminal_venta_id'), table_name='cobros_terminal')
    op.drop_index(op.f('ix_cobros_terminal_orden_id'), table_name='cobros_terminal')
    op.drop_index(op.f('ix_cobros_terminal_caja_id'), table_name='cobros_terminal')
    op.drop_index(op.f('ix_cobros_terminal_negocio_id'), table_name='cobros_terminal')
    op.drop_table('cobros_terminal')
    op.drop_column('cajas', 'terminal_mp')
