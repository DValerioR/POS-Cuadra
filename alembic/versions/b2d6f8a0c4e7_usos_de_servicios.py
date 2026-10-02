"""usos de servicios (IA y facturas) para los topes del plan

Revision ID: b2d6f8a0c4e7
Revises: c7d2e9a4f1b8
Create Date: 2026-10-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2d6f8a0c4e7'
down_revision: Union[str, None] = 'c7d2e9a4f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('usos_servicio',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.Enum('IA', 'FACTURA', name='tipouso'), nullable=False),
    sa.Column('origen', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_usos_servicio_negocio_tipo_fecha', 'usos_servicio', ['negocio_id', 'tipo', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_usos_servicio_negocio_tipo_fecha', table_name='usos_servicio')
    op.drop_table('usos_servicio')
    sa.Enum(name='tipouso').drop(op.get_bind())
