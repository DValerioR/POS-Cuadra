"""bot de whatsapp: conversaciones, mensajes e información para clientes

Revision ID: a2c8e4f6b1d3
Revises: f5b1d7a3c9e6
Create Date: 2026-09-30 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a2c8e4f6b1d3'
down_revision: Union[str, None] = 'f5b1d7a3c9e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ESTADOS = ('BOT', 'ESPERA', 'PERSONA')


def upgrade() -> None:
    op.add_column('negocios', sa.Column('direccion', sa.String(), nullable=True))
    op.add_column('negocios', sa.Column('ubicacion_url', sa.String(), nullable=True))
    op.add_column('negocios', sa.Column('telefono', sa.String(), nullable=True))
    op.add_column('negocios', sa.Column('formas_pago', postgresql.JSONB(), nullable=True))

    estado = postgresql.ENUM(*ESTADOS, name='estadoconversacion')
    estado.create(op.get_bind())
    op.create_table('conversaciones_whatsapp',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('negocio_id', sa.Integer(), nullable=False),
    sa.Column('telefono', sa.String(), nullable=False),
    sa.Column('nombre', sa.String(), nullable=True),
    sa.Column('estado', postgresql.ENUM(*ESTADOS, name='estadoconversacion', create_type=False), nullable=False),
    sa.Column('motivo_persona', sa.String(), nullable=True),
    sa.Column('persona_desde', sa.DateTime(timezone=True), nullable=True),
    sa.Column('atendida_por_id', sa.Integer(), nullable=True),
    sa.Column('aviso_error', sa.String(), nullable=True),
    sa.Column('ultimo_cliente_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_mensaje_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sin_leer', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.ForeignKeyConstraint(['atendida_por_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('negocio_id', 'telefono', name='uq_conversacion_whatsapp_telefono')
    )
    op.create_index(op.f('ix_conversaciones_whatsapp_negocio_id'), 'conversaciones_whatsapp', ['negocio_id'], unique=False)
    op.create_index(op.f('ix_conversaciones_whatsapp_estado'), 'conversaciones_whatsapp', ['estado'], unique=False)
    op.create_index(op.f('ix_conversaciones_whatsapp_ultimo_mensaje_at'), 'conversaciones_whatsapp', ['ultimo_mensaje_at'], unique=False)
    op.create_table('mensajes_whatsapp',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversacion_id', sa.Integer(), nullable=False),
    sa.Column('de', sa.String(), nullable=False),
    sa.Column('texto', sa.String(), nullable=True),
    sa.Column('imagen', sa.LargeBinary(), nullable=True),
    sa.Column('imagen_tipo', sa.String(), nullable=True),
    sa.Column('wa_id', sa.String(), nullable=True),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('error', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversacion_id'], ['conversaciones_whatsapp.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('wa_id')
    )
    op.create_index(op.f('ix_mensajes_whatsapp_conversacion_id'), 'mensajes_whatsapp', ['conversacion_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_mensajes_whatsapp_conversacion_id'), table_name='mensajes_whatsapp')
    op.drop_table('mensajes_whatsapp')
    op.drop_index(op.f('ix_conversaciones_whatsapp_ultimo_mensaje_at'), table_name='conversaciones_whatsapp')
    op.drop_index(op.f('ix_conversaciones_whatsapp_estado'), table_name='conversaciones_whatsapp')
    op.drop_index(op.f('ix_conversaciones_whatsapp_negocio_id'), table_name='conversaciones_whatsapp')
    op.drop_table('conversaciones_whatsapp')
    postgresql.ENUM(name='estadoconversacion').drop(op.get_bind())
    op.drop_column('negocios', 'formas_pago')
    op.drop_column('negocios', 'telefono')
    op.drop_column('negocios', 'ubicacion_url')
    op.drop_column('negocios', 'direccion')
