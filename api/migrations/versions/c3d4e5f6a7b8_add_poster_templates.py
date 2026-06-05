"""add poster_templates

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-06-05

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'poster_templates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('poster_type', sa.String(), nullable=False),
        sa.Column('paper_size', sa.String(), nullable=False),
        sa.Column('orientation', sa.String(), nullable=False),
        sa.Column('params', sa.JSON(), nullable=False),
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('speltak_id', sa.String(36), sa.ForeignKey('speltakken.id'), nullable=True),
        sa.Column('group_id', sa.String(36), sa.ForeignKey('groups.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            '(user_id IS NOT NULL) + (speltak_id IS NOT NULL) + (group_id IS NOT NULL) = 1',
            name='ck_poster_template_one_scope',
        ),
    )
    op.create_index('ix_poster_templates_created_by_id', 'poster_templates', ['created_by_id'])
    op.create_index('ix_poster_templates_user_id', 'poster_templates', ['user_id'])
    op.create_index('ix_poster_templates_speltak_id', 'poster_templates', ['speltak_id'])
    op.create_index('ix_poster_templates_group_id', 'poster_templates', ['group_id'])


def downgrade() -> None:
    op.drop_index('ix_poster_templates_group_id', table_name='poster_templates')
    op.drop_index('ix_poster_templates_speltak_id', table_name='poster_templates')
    op.drop_index('ix_poster_templates_user_id', table_name='poster_templates')
    op.drop_index('ix_poster_templates_created_by_id', table_name='poster_templates')
    op.drop_table('poster_templates')
