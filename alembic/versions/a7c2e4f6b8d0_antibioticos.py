"""antibióticos: marca en productos, médicos y recetas de las ventas

Revision ID: a7c2e4f6b8d0
Revises: f1b3d5a7c9e2
Create Date: 2026-10-03 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a7c2e4f6b8d0'
down_revision: Union[str, None] = 'f1b3d5a7c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('productos', sa.Column('antibiotico', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('productos', sa.Column('antibiotico_manual', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table('medicos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('cedula', sa.String(), nullable=False),
    sa.Column('nombre', sa.String(), nullable=False),
    sa.Column('domicilio', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('negocio_id', 'cedula', name='uq_medico_cedula_por_negocio')
    )
    op.create_index(op.f('ix_medicos_negocio_id'), 'medicos', ['negocio_id'], unique=False)
    op.create_table('recetas_venta',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('venta_id', sa.Integer(), nullable=False),
    sa.Column('medico_id', sa.Integer(), nullable=True),
    sa.Column('medico_nombre', sa.String(), nullable=False),
    sa.Column('cedula', sa.String(), nullable=False),
    sa.Column('domicilio', sa.String(), nullable=True),
    sa.Column('fecha_receta', sa.Date(), nullable=True),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['medico_id'], ['medicos.id'], ),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('venta_id')
    )
    op.create_index(op.f('ix_recetas_venta_negocio_id'), 'recetas_venta', ['negocio_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_recetas_venta_negocio_id'), table_name='recetas_venta')
    op.drop_table('recetas_venta')
    op.drop_index(op.f('ix_medicos_negocio_id'), table_name='medicos')
    op.drop_table('medicos')
    op.drop_column('productos', 'antibiotico_manual')
    op.drop_column('productos', 'antibiotico')
