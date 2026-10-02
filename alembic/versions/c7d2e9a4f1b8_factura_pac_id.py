"""facturas: identificador de la factura en el PAC (Facturapi)

Revision ID: c7d2e9a4f1b8
Revises: a2c8e4f6b1d3
Create Date: 2026-10-01 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7d2e9a4f1b8'
down_revision: Union[str, None] = 'a2c8e4f6b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('facturas', sa.Column('pac_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('facturas', 'pac_id')
