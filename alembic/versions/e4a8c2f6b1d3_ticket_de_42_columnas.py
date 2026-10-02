"""ticket de 42 columnas para todo papel de 80 mm

Revision ID: e4a8c2f6b1d3
Revises: d3e7a1c5f9b2
Create Date: 2026-10-02 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e4a8c2f6b1d3'
down_revision: Union[str, None] = 'd3e7a1c5f9b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 42 columnas caben en cualquier impresora de 80 mm (la Bixolon a 180 dpi
    # no le caben 48); así el ticket sale igual en todas.
    op.alter_column('cajas', 'impresora_columnas', server_default='42')
    op.execute("UPDATE cajas SET impresora_columnas = 42 WHERE impresora_columnas >= 38")


def downgrade() -> None:
    op.execute("UPDATE cajas SET impresora_columnas = 48 WHERE impresora_columnas = 42")
    op.alter_column('cajas', 'impresora_columnas', server_default='48')
