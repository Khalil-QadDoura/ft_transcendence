"""Pydantic response and WebSocket event schemas for Turing Duel rooms.

Every participant payload before results uses identical fields and types for humans and bots:
no user_id, no is_bot, no avatar, and no bot-plan metadata.
Clients identify participants strictly by their 1-based seat number (label number, 1–5),
derived from display_label ("Player N"), never by the internal database participant id.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.game.constants import label_number


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
