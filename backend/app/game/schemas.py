"""Pydantic response and WebSocket event schemas for Turing Duel rooms.

Every participant payload before results uses identical fields and types for humans and bots:
no user_id, no is_bot, no avatar, and no bot-plan metadata.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    room_id: int
    state: str
    phase_ends_at: datetime


class GameParticipantEventOut(BaseModel):
    room_id: int
    participant: ParticipantOut
    participant_count: int
    room_expires_at: datetime | None


class GameMessageEventOut(BaseModel):
    id: int
    participant_id: int
    display_label: str
    text: str


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
