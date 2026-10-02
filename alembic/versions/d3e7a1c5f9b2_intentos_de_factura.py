"""intentos de factura sin confirmar (para reintentar sin duplicar)

Revision ID: d3e7a1c5f9b2
Revises: b2d6f8a0c4e7
Create Date: 2026-10-02 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd3e7a1c5f9b2'
down_revision: Union[str, None] = 'b2d6f8a0c4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('intentos_factura',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('venta_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('serie', sa.String(), nullable=False),
    sa.Column('folio', sa.Integer(), nullable=False),
    sa.Column('pac', sa.String(), nullable=False),
    sa.Column('pac_id', sa.String(), nullable=True),
    sa.Column('datos', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('mensaje', sa.String(), nullable=True),
    sa.Column('intentos', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('negocio_id', 'serie', 'folio', name='uq_intento_factura_folio'),
    sa.UniqueConstraint('venta_id')
    )
    op.create_index(op.f('ix_intentos_factura_negocio_id'), 'intentos_factura', ['negocio_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_intentos_factura_negocio_id'), table_name='intentos_factura')
    op.drop_table('intentos_factura')
