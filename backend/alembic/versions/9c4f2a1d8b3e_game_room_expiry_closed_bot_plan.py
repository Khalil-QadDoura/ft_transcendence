"""Add game_rooms.room_expires_at, game_rooms.bot_plan, and 'closed' room state (BE-27)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c4f2a1d8b3e"
down_revision: str | None = "ed150e2c4d01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE game_room_state ADD VALUE IF NOT EXISTS 'closed'")
    op.add_column("game_rooms", sa.Column("room_expires_at", sa.DateTime(timezone=True)))
    op.add_column("game_rooms", sa.Column("bot_plan", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("game_rooms", "bot_plan")
    op.drop_column("game_rooms", "room_expires_at")

    # PostgreSQL does not support DROP VALUE directly; rebuild the original 4-value enum.
    op.execute("DELETE FROM game_rooms WHERE state = 'closed'")
    op.execute("ALTER TABLE game_rooms ALTER COLUMN state DROP DEFAULT")
    old_enum = postgresql.ENUM(
        "waiting", "discussion", "voting", "finished", name="game_room_state_old"
    )
    old_enum.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE game_rooms "
        "ALTER COLUMN state TYPE game_room_state_old USING state::text::game_room_state_old"
    )
    op.execute("DROP TYPE game_room_state")
    op.execute("ALTER TYPE game_room_state_old RENAME TO game_room_state")
    op.execute("ALTER TABLE game_rooms ALTER COLUMN state SET DEFAULT 'waiting'")
