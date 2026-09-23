"""create users and messages tables

Revision ID: 06c1b9c7b0ec
Revises:
Create Date: 2025-09-03 22:38:14.885452

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '06c1b9c7b0ec'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the initial schema (true initial migration; works on a fresh database)."""
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)

    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(), nullable=False),
        sa.Column(
            'timestamp',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_messages_id'), 'messages', ['id'], unique=False)


def downgrade() -> None:
    """Drop the initial schema."""
    op.drop_index(op.f('ix_messages_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')