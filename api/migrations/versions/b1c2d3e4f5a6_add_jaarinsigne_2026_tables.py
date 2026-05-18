"""add jaarinsigne_2026_min_punten and inclusions table

Revision ID: b1c2d3e4f5a6
Revises: d3e4f5a6b7c8
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('speltakken', sa.Column('jaarinsigne_2026_min_punten', sa.Integer(), nullable=True))

    op.create_table(
        'jaarinsigne_2026_inclusions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('badge_slug', sa.String(), nullable=False),
        sa.Column('level_index', sa.Integer(), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'badge_slug', 'level_index', 'step_index',
                            name='uq_ji2026_inclusion'),
    )
    op.create_index('ix_jaarinsigne_2026_inclusions_user_id',
                    'jaarinsigne_2026_inclusions', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_jaarinsigne_2026_inclusions_user_id',
                  table_name='jaarinsigne_2026_inclusions')
    op.drop_table('jaarinsigne_2026_inclusions')
    op.drop_column('speltakken', 'jaarinsigne_2026_min_punten')
