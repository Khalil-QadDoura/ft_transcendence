"""Turing Duel: rooms, who is in them (people and bots), their chat and their votes."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin

# The server moves a room through these states on its own clock.
ROOM_STATES = ("waiting", "discussion", "voting", "finished", "closed")
GUESSES = ("bot", "human")


class GameRoom(TimestampMixin, Base):
    __tablename__ = "game_rooms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # How many participants the room is for; the game code and its rules (DOC-08) decide.
    target_size: Mapped[int]
    state: Mapped[str] = mapped_column(
        Enum(*ROOM_STATES, name="game_room_state"), server_default="waiting"
    )
    # Set once on room creation (created + 180 s), never extended, used to close/auto-start.
    room_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Server-only hidden bot schedule (never exposed in any schema or WebSocket event).
    bot_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    discussion_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voting_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GameParticipant(TimestampMixin, Base):
    """A player in a room: a person (user_id set) or a bot (user_id empty)."""

    __tablename__ = "game_participants"
    # A person is in a room once. Bots have no user_id, and empty (NULL) values never
    # clash, so a room can hold several bots.
    __table_args__ = (UniqueConstraint("room_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_rooms.id", ondelete="CASCADE")
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # What the others see instead of a name, for example "Player 3".
    display_label: Mapped[str] = mapped_column(String(20))
    score: Mapped[int] = mapped_column(server_default=text("0"))


class GameMessage(TimestampMixin, Base):
    """A chat line in a room, kept so a player who reconnects can catch up."""

    __tablename__ = "game_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_rooms.id", ondelete="CASCADE"), index=True
    )
    participant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_participants.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GameVote(TimestampMixin, Base):
    """One player's guess about another player: bot or human."""

    __tablename__ = "game_votes"
    __table_args__ = (
        # One guess per voter about each other player, and never about themselves.
        # (That both players are in this room is checked in code: BE-10.)
        UniqueConstraint("voter_participant_id", "target_participant_id"),
        CheckConstraint("voter_participant_id <> target_participant_id", name="not_self"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_rooms.id", ondelete="CASCADE"), index=True
    )
    voter_participant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_participants.id", ondelete="CASCADE")
    )
    target_participant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("game_participants.id", ondelete="CASCADE"), index=True
    )
    guess: Mapped[str] = mapped_column(Enum(*GUESSES, name="game_vote_guess"))
