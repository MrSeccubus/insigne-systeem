"""initial schema

Revision ID: 9f5c7199cc32
Revises:
Create Date: 2026-04-21 13:34:40.795181

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '9f5c7199cc32'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(), nullable=False, unique=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('password_hash', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'confirmation_tokens',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('token', sa.String(), nullable=False, unique=True),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_confirmation_tokens_user_id', 'confirmation_tokens', ['user_id'])

    op.create_table(
        'progress_entries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('badge_slug', sa.String(), nullable=False),
        sa.Column('level_index', sa.Integer(), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('mentor_comment', sa.String(), nullable=True),
        sa.Column('signed_off_by_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('signed_off_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_progress_entries_user_id', 'progress_entries', ['user_id'])

    op.create_table(
        'signoff_requests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('progress_entry_id', sa.String(36), sa.ForeignKey('progress_entries.id'), nullable=False),
        sa.Column('mentor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_signoff_requests_progress_entry_id', 'signoff_requests', ['progress_entry_id'])
    op.create_index('ix_signoff_requests_mentor_id', 'signoff_requests', ['mentor_id'])

    op.create_table(
        'signoff_rejections',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('progress_entry_id', sa.String(36), sa.ForeignKey('progress_entries.id'), nullable=False),
        sa.Column('mentor_name', sa.String(), nullable=False),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_signoff_rejections_progress_entry_id', 'signoff_rejections', ['progress_entry_id'])


def downgrade() -> None:
    op.drop_table('signoff_rejections')
    op.drop_table('signoff_requests')
    op.drop_table('progress_entries')
    op.drop_table('confirmation_tokens')
    op.drop_table('users')
