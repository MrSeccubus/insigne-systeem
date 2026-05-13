"""add user favorite badges

Revision ID: b3c4d5e6f7a8
Revises: f4a5b6c7d8e9
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a8'
down_revision = 'a5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_favorite_badges',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('badge_slug', sa.String(100), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table('user_favorite_badges')
