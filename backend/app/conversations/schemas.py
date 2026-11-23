"""Pydantic schemas for conversations, participants, and messages."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The largest id the database can hold (BIGINT). A bigger id in a request is a 422, not a
# database error (BE-13).
MAX_ID = 2**63 - 1

# ── Response Models ────────────────────────────────────────────────────────────


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    author_id: int | None = None
    content: str
    status: str
    message_type: str = "text"
    reply_to_id: int | None = None
    idempotency_key: str | None = None
    edited_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ParticipantOut(BaseModel):
    user_id: int
    role: str
    joined_at: datetime = Field(validation_alias="created_at")
    last_read_message_id: int | None = None
    is_muted: bool = False

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PeerOut(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    display_name: str
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: int
    type: str
    title: str | None = None
    job_id: int | None = None
    job_title: str | None = None
    last_message_id: int | None = None
    last_message_content: str | None = None
    last_message_author_id: int | None = None
    unread_count: int = 0
    updated_at: datetime
    peer: PeerOut | None = None

    model_config = {"from_attributes": True}


class MessagesPage(BaseModel):
    items: list[MessageOut]
    prev_before_id: int | None = None


class UnreadOut(BaseModel):
    total_unread: int


# ── Request Models ─────────────────────────────────────────────────────────────


class ConversationCreate(BaseModel):
    type: Literal["direct", "ai"] = "direct"
    peer_user_id: int | None = Field(default=None, ge=1, le=MAX_ID)
    job_id: int | None = Field(default=None, ge=1, le=MAX_ID)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    reply_to_id: int | None = Field(default=None, ge=1, le=MAX_ID)
    idempotency_key: str | None = Field(default=None, max_length=64)


class EditMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ReadRequest(BaseModel):
    last_message_id: int = Field(gt=0, le=MAX_ID)


class AddParticipantRequest(BaseModel):
    user_id: int = Field(ge=1, le=MAX_ID)
    role: Literal["member", "admin"] = "member"


class SendResponse(BaseModel):
    items: list[MessageOut]
