"""add withdrawn to group and speltak memberships

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-04-21 00:00:02.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('group_memberships',
        sa.Column('withdrawn', sa.Boolean(), nullable=False, server_default='0')
    )
    op.add_column('speltak_memberships',
        sa.Column('withdrawn', sa.Boolean(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    op.drop_column('group_memberships', 'withdrawn')
    op.drop_column('speltak_memberships', 'withdrawn')
