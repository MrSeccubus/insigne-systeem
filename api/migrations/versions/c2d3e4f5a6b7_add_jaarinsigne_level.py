"""add jaarinsigne_levels table

Revision ID: c2d3e4f5a6b7
Revises: b3c4d5e6f7a8
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'c2d3e4f5a6b7'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jaarinsigne_levels',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('badge_slug', sa.String(), nullable=False),
        sa.Column('speltak_slug', sa.String(), nullable=False),
        sa.Column('set_by_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'badge_slug', name='uq_jaarinsigne_level_user_badge'),
    )
    op.create_index('ix_jaarinsigne_levels_user_id', 'jaarinsigne_levels', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_jaarinsigne_levels_user_id', 'jaarinsigne_levels')
    op.drop_table('jaarinsigne_levels')
