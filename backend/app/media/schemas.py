"""Request and response shapes of /api/media (they also appear in /api/openapi.json)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.media.constants import (
    MAX_DURATION_SEC,
    MAX_SIZE_BYTES,
    MAX_URL_EXPIRES_SEC,
    MIN_URL_EXPIRES_SEC,
    MP4_CONTENT_TYPE,
    MP4_EXTENSION,
    UPLOAD_URL_EXPIRES_SEC,
)


class UploadUrlIn(BaseModel):
    """What the browser is about to upload. Anything but an MP4 gets 415: the service checks
    it, not this schema, because a schema error would be 422."""

    content_type: str = MP4_CONTENT_TYPE
    ext: str = MP4_EXTENSION
    expires_sec: int = Field(UPLOAD_URL_EXPIRES_SEC, ge=MIN_URL_EXPIRES_SEC, le=MAX_URL_EXPIRES_SEC)


class UploadUrlOut(BaseModel):
    object_key: str  # where the file will be: users/<my id>/intro/<uuid>.mp4
    put_url: str  # the browser PUTs the file here
    get_url: str  # and can watch it here once it is uploaded
    expires_sec: int
    max_bytes: int  # so the browser can refuse a file that is too big before sending it


class ConfirmIn(BaseModel):
    """Sent once the PUT has finished. duration_sec and size_bytes are what the browser
    reports: the real size is read from storage, and the real duration is measured by the
    moderation worker (BE-29), which opens the video."""

    object_key: str = Field(max_length=500)  # the size of the object_key column
    duration_sec: int = Field(ge=1, le=MAX_DURATION_SEC)
    size_bytes: int = Field(ge=1, le=MAX_SIZE_BYTES)
    content_type: Literal["video/mp4"]


class VideoStatusOut(BaseModel):
    """The answer of confirm, post, unpost and delete."""

    model_config = ConfigDict(from_attributes=True)  # read the fields from an IntroVideo row

    id: int
    moderation_status: str
    lifecycle_status: str


class MyVideoOut(BaseModel):
    """One of my videos, with a signed link to watch it (it works for expires_sec seconds)."""

    id: int
    object_key: str
    duration_sec: int
    size_bytes: int
    content_type: str
    moderation_status: str
    rejected_reason: str | None = None
    lifecycle_status: str
    created_at: datetime
    updated_at: datetime
    signed_url: str
    expires_sec: int


class MyVideosOut(BaseModel):
    items: list[MyVideoOut]


class FeedVideoOut(BaseModel):
    """A video in the feed, with its author and a signed link to watch it."""

    id: int
    user_id: int
    duration_sec: int
    size_bytes: int
    content_type: str
    signed_url: str
    expires_sec: int
    created_at: datetime
    author_name: str | None  # "first last", or null when the profile has neither
    author_position: str | None


class FeedOut(BaseModel):
    items: list[FeedVideoOut]
    # The id to send as ?cursor= for the next page; null on the last page.
    next_cursor: int | None


class PictureUploadUrlOut(BaseModel):
    """The answer of avatar/upload-url and company-logo/upload-url (BE-08)."""

    # Where the browser uploads the picture, in a private folder nobody can download from:
    # staging/avatars/<my id>/<uuid>.png, for example. confirm publishes a copy elsewhere.
    object_key: str
    put_url: str  # the browser PUTs the file here
    expires_sec: int
    max_bytes: int  # so the browser can refuse a picture that is too big before sending it


class PictureConfirmIn(BaseModel):
    """Sent once the PUT has finished: the object_key that upload-url gave (staging/...)."""

    object_key: str = Field(max_length=500)  # the size of the avatar and logo key columns
