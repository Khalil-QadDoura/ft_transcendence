"""Add users.deleted_at, users.retention_hold and users.anonymised_at (BE-34).

Revision ID: 1e0ebc1aa098
Revises: 9c4f2a1d8b3e
Create Date: 2026-11-23 12:00:00

An account is deleted in two stages (Privacy Policy, section 6): DELETE /api/users/me
deactivates it at once, and the daily job of the worker anonymises it 30 days later.

- deleted_at: when the account was deleted. The job counts the 30 days from it.
- retention_hold: set by hand by the team while a complaint or dispute about the account is
  open; the job skips the account until it is false again.
- anonymised_at: when the job anonymised the account; the job never picks it again.

Accounts deleted before this migration get their last update as deleted_at: nothing changes
a deleted account, so it is the closest record of when the deletion happened.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1e0ebc1aa098"
down_revision: str | None = "9c4f2a1d8b3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column(
        "users",
        sa.Column("retention_hold", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("users", sa.Column("anonymised_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE users SET deleted_at = updated_at WHERE status = 'deleted'")


def downgrade() -> None:
    op.drop_column("users", "anonymised_at")
    op.drop_column("users", "retention_hold")
    op.drop_column("users", "deleted_at")
