"""add invited_by_id to group and speltak memberships

Revision ID: a1b2c3d4e5f6
Revises: 63f0c6ea2f45
Create Date: 2026-04-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '63f0c6ea2f45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite does not support ADD COLUMN with FK constraints; the FK is enforced
    # at the ORM level via the relationship, not at the DB level.
    op.add_column('group_memberships',
        sa.Column('invited_by_id', sa.String(36), nullable=True)
    )
    op.add_column('speltak_memberships',
        sa.Column('invited_by_id', sa.String(36), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('group_memberships', 'invited_by_id')
    op.drop_column('speltak_memberships', 'invited_by_id')
