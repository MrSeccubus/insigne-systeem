"""add source_scout_id to speltak_memberships

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite does not support ADD COLUMN with FK constraints; FK is enforced at ORM level.
    op.add_column('speltak_memberships',
        sa.Column('source_scout_id', sa.String(36), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('speltak_memberships', 'source_scout_id')
