"""Pydantic response and WebSocket event schemas for Turing Duel rooms.

Every participant payload before results uses identical fields and types for humans and bots:
no user_id, no is_bot, no avatar, and no bot-plan metadata.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.game.constants import MAX_PARTICIPANTS


class QueueJoinOut(BaseModel):
    message: str = "queued"
    room_id: int


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_label: str


class RoomParticipantOut(BaseModel):
    id: int
    display_label: str
    is_you: bool


class RoomOut(BaseModel):
    id: int
    state: str
    target_size: int
    participant_count: int
    my_participant_id: int
    room_expires_at: datetime | None
    phase_ends_at: datetime | None
    participants: list[RoomParticipantOut]


class GameRoomEventOut(BaseModel):
    room_id: int


class GamePhaseEventOut(BaseModel):
    """game_started, game_phase_voting and game_phase_finished (no end time once finished)."""

    room_id: int
    state: str
    phase_ends_at: datetime | None


class GameParticipantEventOut(BaseModel):
    room_id: int
    participant: ParticipantOut
    participant_count: int
    room_expires_at: datetime | None


class VoteIn(BaseModel):
    """A voter's mark on one other participant, named by its label number ("Player 3" -> 3)."""

    target_participant_id: int = Field(ge=1, le=MAX_PARTICIPANTS)
    guess: Literal["bot", "human"]


class VoteOut(BaseModel):
    target_participant_id: int
    guess: Literal["bot", "human"]


class ParticipantResultOut(BaseModel):
    """One participant in the results; ids are label numbers, as in every game payload."""

    participant_id: int
    display_label: str
    is_bot: bool
    score: int | None  # humans only
    outcome: Literal["win", "draw", "loss"] | None  # humans only
    deception_rate: int | None  # bots only: percentage 0-100


class RoomResultsOut(BaseModel):
    room_id: int
    state: str
    my_participant_id: int
    winner_participant_ids: list[int]
    is_draw: bool
    participants: list[ParticipantResultOut]


class GameMessageEventOut(BaseModel):
    id: int
    participant_id: int
    display_label: str
    text: str
