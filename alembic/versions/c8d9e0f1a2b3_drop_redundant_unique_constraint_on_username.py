"""drop the redundant unique constraint on users.username

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-25 22:40:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Keep the unique index the model declares, drop the duplicate constraint.

    The initial migration created both `users_username_key` (a UNIQUE
    constraint) and `ix_users_username` (a unique index) for the same column,
    while `User.username` declares `unique=True, index=True` — one index. The
    two enforce uniqueness identically, so the constraint is dead weight that
    made `alembic check` report drift on every autogenerate run. Uniqueness is
    unchanged: the unique index remains.
    """
    op.drop_constraint('users_username_key', 'users', type_='unique')


def downgrade() -> None:
    """Put the constraint back; the unique index already guarantees uniqueness."""
    op.create_unique_constraint('users_username_key', 'users', ['username'])