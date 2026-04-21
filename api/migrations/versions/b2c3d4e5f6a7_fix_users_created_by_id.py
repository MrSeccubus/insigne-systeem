"""ensure users.created_by_id exists (repair for databases stamped before migration ran)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-21 00:00:01.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = [col['name'] for col in inspect(bind).get_columns('users')]
    if 'created_by_id' not in existing:
        with op.batch_alter_table('users') as batch_op:
            batch_op.add_column(sa.Column('created_by_id', sa.String(36), nullable=True))


def downgrade() -> None:
    pass
