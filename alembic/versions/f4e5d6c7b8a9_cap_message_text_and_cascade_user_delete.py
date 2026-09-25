"""cap message text length and cascade user deletion

Revision ID: f4e5d6c7b8a9
Revises: 1a2b3c4d5e6f
Create Date: 2026-09-25 19:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4e5d6c7b8a9'
down_revision: Union[str, Sequence[str], None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cap `messages.text` at 4000 and make user deletion cascade (gaps D6, D4).

    Existing rows cannot exceed 4000 characters: every write went through
    `MessageCreate.text`'s Pydantic `max_length=4000` (gap B3).
    """
    op.alter_column(
        'messages',
        'text',
        type_=sa.String(length=4000),
        existing_type=sa.String(),
        existing_nullable=False,
    )
    op.drop_constraint('messages_user_id_fkey', 'messages', type_='foreignkey')
    op.create_foreign_key(
        'messages_user_id_fkey',
        'messages',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    """Remove the cascade and restore the unbounded text column."""
    op.drop_constraint('messages_user_id_fkey', 'messages', type_='foreignkey')
    op.create_foreign_key(
        'messages_user_id_fkey',
        'messages',
        'users',
        ['user_id'],
        ['id'],
    )
    op.alter_column(
        'messages',
        'text',
        type_=sa.String(),
        existing_type=sa.String(length=4000),
        existing_nullable=False,
    )
