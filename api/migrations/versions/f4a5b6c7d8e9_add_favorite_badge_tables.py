"""add favorite badge tables

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-04-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'speltak_favorite_badges',
        sa.Column('speltak_id', sa.String(36), sa.ForeignKey('speltakken.id'), primary_key=True),
        sa.Column('badge_slug', sa.String(100), primary_key=True),
    )
    op.create_table(
        'group_favorite_badges',
        sa.Column('group_id', sa.String(36), sa.ForeignKey('groups.id'), primary_key=True),
        sa.Column('badge_slug', sa.String(100), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table('speltak_favorite_badges')
    op.drop_table('group_favorite_badges')
