"""ofertas en la venta

Revision ID: f1a2b3c4d5e6
Revises: b0ddf1565304
Create Date: 2026-09-30 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'b0ddf1565304'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ofertas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('producto_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(), nullable=False),
    sa.Column('precio', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('paquete_con_id', sa.Integer(), nullable=True),
    sa.Column('inicio', sa.Date(), nullable=False),
    sa.Column('fin', sa.Date(), nullable=False),
    sa.Column('activa', sa.Boolean(), nullable=False),
    sa.Column('motivo', sa.String(), nullable=True),
    sa.Column('origen', sa.String(), nullable=False),
    sa.Column('creada_por_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('quitada_por_id', sa.Integer(), nullable=True),
    sa.Column('quitada_en', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], ),
    sa.ForeignKeyConstraint(['paquete_con_id'], ['productos.id'], ),
    sa.ForeignKeyConstraint(['creada_por_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['quitada_por_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ofertas_negocio_id'), 'ofertas', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_ofertas_producto_id'), 'ofertas', ['producto_id'], unique=False)
    op.create_index(op.f('ix_ofertas_paquete_con_id'), 'ofertas', ['paquete_con_id'], unique=False)
    op.add_column('venta_renglones', sa.Column('descuento', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('venta_renglones', sa.Column('oferta_id', sa.Integer(), nullable=True))
    op.add_column('venta_renglones', sa.Column('oferta_texto', sa.String(), nullable=True))
    op.create_foreign_key('venta_renglones_oferta_id_fkey', 'venta_renglones', 'ofertas', ['oferta_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('venta_renglones_oferta_id_fkey', 'venta_renglones', type_='foreignkey')
    op.drop_column('venta_renglones', 'oferta_texto')
    op.drop_column('venta_renglones', 'oferta_id')
    op.drop_column('venta_renglones', 'descuento')
    op.drop_index(op.f('ix_ofertas_paquete_con_id'), table_name='ofertas')
    op.drop_index(op.f('ix_ofertas_producto_id'), table_name='ofertas')
    op.drop_index(op.f('ix_ofertas_negocio_id'), table_name='ofertas')
    op.drop_table('ofertas')
