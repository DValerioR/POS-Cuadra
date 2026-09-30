"""encargos

Revision ID: c9e5a3b7d2f1
Revises: b8d4f2a6c1e3
Create Date: 2026-09-30 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c9e5a3b7d2f1'
down_revision: Union[str, None] = 'b8d4f2a6c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ESTADOS = ('POR_PEDIR', 'PEDIDO', 'LLEGO', 'ENTREGADO', 'CANCELADO')


def upgrade() -> None:
    op.add_column('productos', sa.Column('encargo', sa.Boolean(), server_default=sa.false(), nullable=False))
    estado = postgresql.ENUM(*ESTADOS, name='estadoencargo')
    estado.create(op.get_bind())
    op.create_table('encargos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('producto_id', sa.Integer(), nullable=True),
    sa.Column('descripcion', sa.String(), nullable=False),
    sa.Column('cantidad', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('cliente', sa.String(), nullable=False),
    sa.Column('telefono', sa.String(), nullable=True),
    sa.Column('canal', sa.String(), server_default='mostrador', nullable=False),
    sa.Column('notas', sa.String(), nullable=True),
    sa.Column('estado', postgresql.ENUM(*ESTADOS, name='estadoencargo', create_type=False), nullable=False),
    sa.Column('pedido_id', sa.Integer(), nullable=True),
    sa.Column('avisado_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('avisado_estado', postgresql.ENUM(*ESTADOS, name='estadoencargo', create_type=False), nullable=True),
    sa.Column('creado_por_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], ),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.ForeignKeyConstraint(['creado_por_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_encargos_negocio_id'), 'encargos', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_encargos_producto_id'), 'encargos', ['producto_id'], unique=False)
    op.create_index(op.f('ix_encargos_estado'), 'encargos', ['estado'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_encargos_estado'), table_name='encargos')
    op.drop_index(op.f('ix_encargos_producto_id'), table_name='encargos')
    op.drop_index(op.f('ix_encargos_negocio_id'), table_name='encargos')
    op.drop_table('encargos')
    postgresql.ENUM(name='estadoencargo').drop(op.get_bind())
    op.drop_column('productos', 'encargo')
