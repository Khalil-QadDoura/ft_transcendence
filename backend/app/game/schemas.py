"""Pydantic response and WebSocket event schemas for Turing Duel rooms.

Every participant payload before results uses identical fields and types for humans and bots:
no user_id, no is_bot, no avatar, and no bot-plan metadata.
Clients identify participants strictly by their 1-based seat number (label number, 1–5),
derived from display_label ("Player N"), never by the internal database participant id.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game.constants import MAX_PARTICIPANTS, label_number


class QueueJoinOut(BaseModel):
    message: str = "queued"
    room_id: int


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_label: str

    @model_validator(mode="before")
    @classmethod
    def _enforce_label_number(cls, data: Any) -> Any:
        if isinstance(data, dict):
            label = data.get("display_label")
            if label:
                data = dict(data)
                data["id"] = label_number(str(label))
            return data
        label = getattr(data, "display_label", None)
        if label is not None:
            return {"id": label_number(str(label)), "display_label": label}
        return data


class RoomParticipantOut(BaseModel):
    id: int
    display_label: str
    is_you: bool

    @model_validator(mode="before")
    @classmethod
    def _enforce_label_number(cls, data: Any) -> Any:
        if isinstance(data, dict):
            label = data.get("display_label")
            if label:
                data = dict(data)
                data["id"] = label_number(str(label))
            return data
        label = getattr(data, "display_label", None)
        if label is not None:
            return {
                "id": label_number(str(label)),
                "display_label": label,
                "is_you": bool(getattr(data, "is_you", False)),
            }
        return data


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

    @model_validator(mode="before")
    @classmethod
    def _enforce_label_number(cls, data: Any) -> Any:
        if isinstance(data, dict):
            label = data.get("display_label")
            if label:
                data = dict(data)
                data["participant_id"] = label_number(str(label))
            return data
        label = getattr(data, "display_label", None)
        if label is not None:
            return {
                "id": getattr(data, "id", 0),
                "participant_id": label_number(str(label)),
                "display_label": label,
                "text": getattr(data, "text", ""),
            }
        return data


class GameMessagesPage(BaseModel):
    """GET /api/game/rooms/{id}/messages: oldest to newest. `prev_before_id` asks for the
    page before this one; null means this page starts the chat."""

    items: list[GameMessageEventOut]
    prev_before_id: int | None


class MyVoteOut(BaseModel):
    """One mark I saved: the label number of the participant I marked, and my guess."""

    target_participant_id: int
    guess: str


class GameSnapshotOut(BaseModel):
    """The first frame of every /ws/game connection: the room as it is now, so a reload or a
    lost connection loses nothing. Like every payload before the results, it names each
    participant by label number 1-5 and has no bot flag."""

    room: RoomOut
    messages: list[GameMessageEventOut]
    my_votes: list[MyVoteOut]


class GameErrorOut(BaseModel):
    """Why the server refused a frame sent on /ws/game, e.g. chat outside the discussion."""

    detail: str
