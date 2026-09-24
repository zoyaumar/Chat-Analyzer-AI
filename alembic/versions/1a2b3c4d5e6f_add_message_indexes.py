"""add message query indexes

Revision ID: 1a2b3c4d5e6f
Revises: 06c1b9c7b0ec
Create Date: 2026-09-24 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = '06c1b9c7b0ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes for message queries (pagination, user scoping, daily summary)."""
    op.create_index(op.f('ix_messages_user_id'), 'messages', ['user_id'], unique=False)
    op.create_index(op.f('ix_messages_timestamp'), 'messages', ['timestamp'], unique=False)
    op.create_index(
        'ix_messages_user_id_timestamp_desc',
        'messages',
        ['user_id', 'timestamp'],
        unique=False,
        postgresql_ops={'timestamp': 'DESC'},
    )


def downgrade() -> None:
    """Remove message query indexes."""
    op.drop_index('ix_messages_user_id_timestamp_desc', table_name='messages')
    op.drop_index(op.f('ix_messages_timestamp'), table_name='messages')
    op.drop_index(op.f('ix_messages_user_id'), table_name='messages')
