"""add row timestamps and persisted message sentiment

Revision ID: b7c8d9e0f1a2
Revises: f4e5d6c7b8a9
Create Date: 2026-09-25 22:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'f4e5d6c7b8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Timestamps as `timestamptz` + one persisted score per message.

    `created_at`/`updated_at` are `timezone=True` so a stored value means an
    instant, not a wall clock reading; the summariser and the sentiment model
    write into the same database, so their rows must agree on what "now" is.
    The backfill uses `now()` rather than a fixed date: existing rows are given
    the migration instant, which is the best available approximation.
    """
    op.add_column(
        'users',
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    op.add_column(
        'users', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'messages', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        'message_sentiment',
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=32), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('model_name', sa.String(length=255), nullable=False),
        sa.Column('model_version', sa.String(length=64), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('message_id'),
    )


def downgrade() -> None:
    """Drop the stored scores and the row timestamps."""
    op.drop_table('message_sentiment')
    op.drop_column('messages', 'updated_at')
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'created_at')