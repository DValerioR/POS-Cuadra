"""cancelación de facturas ante el SAT y factura global al público en general

Revision ID: f1b3d5a7c9e2
Revises: e4a8c2f6b1d3
Create Date: 2026-10-03 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f1b3d5a7c9e2'
down_revision: Union[str, None] = 'e4a8c2f6b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # El valor nuevo del enum va en su propio bloque: Postgres no deja usarlo
    # en la misma transacción en la que se agrega.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE estadofactura ADD VALUE IF NOT EXISTS 'CANCELACION_PENDIENTE'")

    op.add_column('facturas', sa.Column('tipo', sa.String(), server_default='ticket', nullable=False))
    op.alter_column('facturas', 'venta_id', existing_type=sa.Integer(), nullable=True)
    op.alter_column('facturas', 'cliente_id', existing_type=sa.Integer(), nullable=True)
    # Un ticket se factura una vez, pero si esa factura se cancela se puede volver a facturar.
    op.drop_constraint('facturas_venta_id_key', 'facturas', type_='unique')
    op.create_index('uq_factura_venta_vigente', 'facturas', ['venta_id'], unique=True,
                    postgresql_where=sa.text("estado <> 'CANCELADA'"))
    for nombre, tipo in (('global_periodicidad', sa.String()), ('global_meses', sa.String()),
                         ('global_anio', sa.Integer()), ('global_desde', sa.Date()), ('global_hasta', sa.Date()),
                         ('cancelacion_motivo', sa.String()),
                         ('cancelacion_solicitada_at', sa.DateTime(timezone=True)),
                         ('cancelada_at', sa.DateTime(timezone=True)), ('cancelacion_mensaje', sa.String()),
                         ('cancelado_por_id', sa.Integer())):
        op.add_column('facturas', sa.Column(nombre, tipo, nullable=True))
    op.create_foreign_key('facturas_cancelado_por_id_fkey', 'facturas', 'usuarios', ['cancelado_por_id'], ['id'])

    op.add_column('intentos_factura', sa.Column('tipo', sa.String(), server_default='ticket', nullable=False))
    op.alter_column('intentos_factura', 'venta_id', existing_type=sa.Integer(), nullable=True)

    op.create_table('ventas_en_global',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('venta_id', sa.Integer(), nullable=False),
    sa.Column('factura_id', sa.Integer(), nullable=True),
    sa.Column('intento_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['factura_id'], ['facturas.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['intento_id'], ['intentos_factura.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('venta_id')
    )
    op.create_index(op.f('ix_ventas_en_global_negocio_id'), 'ventas_en_global', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_ventas_en_global_factura_id'), 'ventas_en_global', ['factura_id'], unique=False)
    op.create_index(op.f('ix_ventas_en_global_intento_id'), 'ventas_en_global', ['intento_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ventas_en_global_intento_id'), table_name='ventas_en_global')
    op.drop_index(op.f('ix_ventas_en_global_factura_id'), table_name='ventas_en_global')
    op.drop_index(op.f('ix_ventas_en_global_negocio_id'), table_name='ventas_en_global')
    op.drop_table('ventas_en_global')
    # Las globales no tienen venta: no caben en el esquema anterior.
    op.execute("DELETE FROM intentos_factura WHERE venta_id IS NULL")
    op.execute("DELETE FROM facturas WHERE venta_id IS NULL")
    op.alter_column('intentos_factura', 'venta_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('intentos_factura', 'tipo')
    op.drop_constraint('facturas_cancelado_por_id_fkey', 'facturas', type_='foreignkey')
    for nombre in ('cancelado_por_id', 'cancelacion_mensaje', 'cancelada_at', 'cancelacion_solicitada_at',
                   'cancelacion_motivo', 'global_hasta', 'global_desde', 'global_anio', 'global_meses',
                   'global_periodicidad'):
        op.drop_column('facturas', nombre)
    op.drop_index('uq_factura_venta_vigente', table_name='facturas')
    op.create_unique_constraint('facturas_venta_id_key', 'facturas', ['venta_id'])
    op.alter_column('facturas', 'cliente_id', existing_type=sa.Integer(), nullable=False)
    op.alter_column('facturas', 'venta_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('facturas', 'tipo')
    # El valor CANCELACION_PENDIENTE del enum se queda: Postgres no permite quitarlo.
    op.execute("UPDATE facturas SET estado = 'VIGENTE' WHERE estado = 'CANCELACION_PENDIENTE'")
