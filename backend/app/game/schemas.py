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
