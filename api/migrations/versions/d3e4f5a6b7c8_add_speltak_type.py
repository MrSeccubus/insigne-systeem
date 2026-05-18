"""add speltak_type to speltakken

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('speltakken', sa.Column('speltak_type', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('speltakken', 'speltak_type')
