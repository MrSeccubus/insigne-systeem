"""add email_change_requests table

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-04-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'a5b6c7d8e9f0'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'email_change_requests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('old_email', sa.String(), nullable=False),
        sa.Column('new_email', sa.String(), nullable=False),
        sa.Column('confirm_token', sa.String(), nullable=False, unique=True),
        sa.Column('revert_token', sa.String(), nullable=False, unique=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revert_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_email_change_requests_user_id', 'email_change_requests', ['user_id'])
    op.create_index('ix_email_change_requests_confirm_token', 'email_change_requests', ['confirm_token'], unique=True)
    op.create_index('ix_email_change_requests_revert_token', 'email_change_requests', ['revert_token'], unique=True)


def downgrade() -> None:
    op.drop_table('email_change_requests')
