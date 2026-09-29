"""imagen de inicio del negocio

Revision ID: b7e4a1c9d2f3
Revises: 9c98f7cda958
Create Date: 2026-09-29 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e4a1c9d2f3'
down_revision: Union[str, None] = '9c98f7cda958'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('negocios', sa.Column('logo_imagen', sa.LargeBinary(), nullable=True))
    op.add_column('negocios', sa.Column('logo_tipo', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('negocios', 'logo_tipo')
    op.drop_column('negocios', 'logo_imagen')
