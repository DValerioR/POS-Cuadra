"""avisos de inventario

Revision ID: c4f2a8d1e9b3
Revises: a3d91c6e4b27
Create Date: 2026-09-29 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4f2a8d1e9b3'
down_revision: Union[str, None] = 'a3d91c6e4b27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('avisos_inventario',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('producto_id', sa.Integer(), nullable=False),
    sa.Column('venta_id', sa.Integer(), nullable=False),
    sa.Column('caja_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('vendidas', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('faltantes', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('estado', sa.Enum('PENDIENTE', 'REVISADO', name='estadoaviso'), nullable=False),
    sa.Column('revisado_por_id', sa.Integer(), nullable=True),
    sa.Column('revisado_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('conteo', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['caja_id'], ['cajas.id'], ),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], ),
    sa.ForeignKeyConstraint(['revisado_por_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_avisos_inventario_estado'), 'avisos_inventario', ['estado'], unique=False)
    op.create_index(op.f('ix_avisos_inventario_negocio_id'), 'avisos_inventario', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_avisos_inventario_producto_id'), 'avisos_inventario', ['producto_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_avisos_inventario_producto_id'), table_name='avisos_inventario')
    op.drop_index(op.f('ix_avisos_inventario_negocio_id'), table_name='avisos_inventario')
    op.drop_index(op.f('ix_avisos_inventario_estado'), table_name='avisos_inventario')
    op.drop_table('avisos_inventario')
    sa.Enum(name='estadoaviso').drop(op.get_bind())
