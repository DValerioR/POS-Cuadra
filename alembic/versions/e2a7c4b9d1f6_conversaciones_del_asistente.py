"""conversaciones del asistente

Revision ID: e2a7c4b9d1f6
Revises: 0dd4042c31fe
Create Date: 2026-09-29 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e2a7c4b9d1f6'
down_revision: Union[str, None] = '0dd4042c31fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('conversaciones_asistente',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversaciones_asistente_negocio_id'), 'conversaciones_asistente', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_conversaciones_asistente_usuario_id'), 'conversaciones_asistente', ['usuario_id'], unique=False)
    op.create_table('mensajes_asistente',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversacion_id', sa.Integer(), nullable=False),
    sa.Column('rol', sa.String(), nullable=False),
    sa.Column('contenido', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('tokens_entrada', sa.Integer(), nullable=True),
    sa.Column('tokens_salida', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversacion_id'], ['conversaciones_asistente.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mensajes_asistente_conversacion_id'), 'mensajes_asistente', ['conversacion_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_mensajes_asistente_conversacion_id'), table_name='mensajes_asistente')
    op.drop_table('mensajes_asistente')
    op.drop_index(op.f('ix_conversaciones_asistente_usuario_id'), table_name='conversaciones_asistente')
    op.drop_index(op.f('ix_conversaciones_asistente_negocio_id'), table_name='conversaciones_asistente')
    op.drop_table('conversaciones_asistente')
