"""solicitudes de devolucion

Revision ID: a3d91c6e4b27
Revises: ec5feedba685
Create Date: 2026-09-29 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a3d91c6e4b27'
down_revision: Union[str, None] = 'ec5feedba685'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('solicitudes_devolucion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('venta_id', sa.Integer(), nullable=False),
    sa.Column('caja_id', sa.Integer(), nullable=False),
    sa.Column('solicitada_por_id', sa.Integer(), nullable=False),
    sa.Column('tipo', postgresql.ENUM('CANCELACION', 'DEVOLUCION', 'CAMBIO', name='tipodevolucion', create_type=False), nullable=False),
    sa.Column('motivo', sa.String(), nullable=False),
    sa.Column('piezas', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('efectivo', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('tarjeta', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('estado', sa.Enum('PENDIENTE', 'AUTORIZADA', 'RECHAZADA', name='estadosolicitud'), nullable=False),
    sa.Column('resuelta_por_id', sa.Integer(), nullable=True),
    sa.Column('resuelta_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('respuesta', sa.String(), nullable=True),
    sa.Column('devolucion_id', sa.Integer(), nullable=True),
    sa.Column('vista', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['caja_id'], ['cajas.id'], ),
    sa.ForeignKeyConstraint(['devolucion_id'], ['devoluciones.id'], ),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['resuelta_por_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['solicitada_por_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_solicitudes_devolucion_caja_id'), 'solicitudes_devolucion', ['caja_id'], unique=False)
    op.create_index(op.f('ix_solicitudes_devolucion_estado'), 'solicitudes_devolucion', ['estado'], unique=False)
    op.create_index(op.f('ix_solicitudes_devolucion_negocio_id'), 'solicitudes_devolucion', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_solicitudes_devolucion_venta_id'), 'solicitudes_devolucion', ['venta_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_solicitudes_devolucion_venta_id'), table_name='solicitudes_devolucion')
    op.drop_index(op.f('ix_solicitudes_devolucion_negocio_id'), table_name='solicitudes_devolucion')
    op.drop_index(op.f('ix_solicitudes_devolucion_estado'), table_name='solicitudes_devolucion')
    op.drop_index(op.f('ix_solicitudes_devolucion_caja_id'), table_name='solicitudes_devolucion')
    op.drop_table('solicitudes_devolucion')
    sa.Enum(name='estadosolicitud').drop(op.get_bind())
