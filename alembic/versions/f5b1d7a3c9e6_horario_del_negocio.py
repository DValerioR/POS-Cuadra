"""negocios: horario de atención

Revision ID: f5b1d7a3c9e6
Revises: e3a9c5d1f7b4
Create Date: 2026-09-30 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f5b1d7a3c9e6'
down_revision: Union[str, None] = 'e3a9c5d1f7b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('negocios', sa.Column('horario', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('negocios', 'horario')
