"""producto no caduca

Revision ID: a3d5f7b9c1e2
Revises: e2a7c4b9d1f6
Create Date: 2026-09-29 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a3d5f7b9c1e2'
down_revision: Union[str, None] = 'e2a7c4b9d1f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('productos', sa.Column('no_caduca', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column('productos', 'no_caduca')
