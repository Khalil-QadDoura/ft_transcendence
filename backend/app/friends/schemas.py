"""Pydantic schemas for friend requests, friends list, and public user profiles."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.media.constants import MAX_ID

FriendshipStatusView = Literal["pending_sent", "pending_received", "accepted"]


class FriendRequestCreate(BaseModel):
    """Payload for POST /api/friends/requests."""

    addressee_id: int = Field(ge=1, le=MAX_ID)


class FriendshipOut(BaseModel):
    """Serialized friendship request or accepted relationship."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    requester_id: int
    addressee_id: int
    status: str
    created_at: datetime


class FriendOut(BaseModel):
    """Single-query friend summary with public avatar URL and live online status."""

    friendship_id: int
    user_id: int
    first_name: str | None
    last_name: str | None
    position: str | None
    avatar_object_key: str | None
    avatar_url: str
    is_online: bool


class PublicProfileOut(BaseModel):
    """Public profile of another (or current) active user with friendship status."""

    id: int
    first_name: str | None
    last_name: str | None
    position: str | None
    bio: str | None
    avatar_object_key: str | None
    avatar_url: str
    is_online: bool
    friendship_status: FriendshipStatusView | None
    friendship_id: int | None = None
