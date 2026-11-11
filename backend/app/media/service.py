"""The rules of intro videos. Routes call these functions; these call the repo and storage."""

import asyncio
import re
from datetime import timedelta
from uuid import uuid4

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import TaskQueue
from app.core.storage import Storage
from app.media import repo
from app.media.constants import (
    MAX_ACTIVE_VIDEOS,
    MAX_SIZE_BYTES,
    MP4_CONTENT_TYPE,
    MP4_EXTENSION,
    MP4_SIGNATURE,
    MP4_SIGNATURE_END,
    MP4_SIGNATURE_START,
    UUID_PATTERN,
)
from app.media.models import IntroVideo
from app.media.schemas import ConfirmIn, MyVideoOut, MyVideosOut, UploadUrlIn, UploadUrlOut
from app.users.models import User

ONLY_MP4 = "Only MP4 videos (video/mp4) are accepted"
NOT_YOUR_KEY = "Invalid object_key: use the one upload-url gave you"
TOO_MANY_VIDEOS = f"You already have {MAX_ACTIVE_VIDEOS} videos: delete one to add a new one"
NO_FILE = "No uploaded file at this object_key: PUT the video to put_url first"
TOO_BIG = f"The video is larger than {MAX_SIZE_BYTES // (1024 * 1024)} MiB"
NOT_AN_MP4 = "The uploaded file is not an MP4 video"
ALREADY_CONFIRMED = "This video is already confirmed"
VIDEO_NOT_FOUND = "Video not found"
NOT_APPROVED = "Only a video approved by moderation can be posted"
ALREADY_POSTED = "This video is already posted"
NOT_POSTED = "This video is not posted"


def object_key_for(user_id: int) -> str:
    """A new, unguessable place for one of this user's videos."""
    return f"users/{user_id}/intro/{uuid4()}.{MP4_EXTENSION}"


def is_my_object_key(user_id: int, object_key: str) -> bool:
    """True only for a key upload-url could have made for this user. fullmatch: the whole key
    must fit the pattern, so "users/1/intro/../2/..." or a key of another user never does."""
    pattern = rf"users/{user_id}/intro/{UUID_PATTERN}\.{MP4_EXTENSION}"
    return re.fullmatch(pattern, object_key) is not None


def looks_like_mp4(first_bytes: bytes) -> bool:
    """MP4 files have the letters "ftyp" at bytes 4 to 7, whatever the file is called."""
    return first_bytes[MP4_SIGNATURE_START:MP4_SIGNATURE_END] == MP4_SIGNATURE


def create_upload_url(storage: Storage, user: User, data: UploadUrlIn) -> UploadUrlOut:
    """A key of my own and two signed links for it: one to upload, one to watch."""
    if data.content_type.lower() != MP4_CONTENT_TYPE or data.ext.lower() != MP4_EXTENSION:
        raise HTTPException(status_code=415, detail=ONLY_MP4)
    object_key = object_key_for(user.id)
    expires = timedelta(seconds=data.expires_sec)
    return UploadUrlOut(
        object_key=object_key,
        put_url=storage.upload_url(object_key, expires),
        get_url=storage.download_url(object_key, expires),
        expires_sec=data.expires_sec,
        max_bytes=MAX_SIZE_BYTES,
    )


async def confirm_upload(
    session: AsyncSession,
    storage: Storage,
    queue: TaskQueue,
    background: BackgroundTasks,
    user: User,
    data: ConfirmIn,
) -> IntroVideo:
    """Check the uploaded file itself, save the video as pending, and queue its moderation."""
    # 1. The key must be one of mine: nobody can confirm another user's file.
    if not is_my_object_key(user.id, data.object_key):
        raise HTTPException(status_code=400, detail=NOT_YOUR_KEY)
    if await repo.count_active_videos(session, user.id) >= MAX_ACTIVE_VIDEOS:
        raise HTTPException(status_code=409, detail=TOO_MANY_VIDEOS)

    # 2. Look at the file in storage instead of trusting what the browser says about it.
    # The MinIO calls wait for the network, so they run in a worker thread.
    size = await asyncio.to_thread(storage.size, data.object_key)
    if size is None:  # never uploaded, or uploaded somewhere else
        raise HTTPException(status_code=400, detail=NO_FILE)
    if size > MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=TOO_BIG)
    first_bytes = await asyncio.to_thread(storage.first_bytes, data.object_key, MP4_SIGNATURE_END)
    if not looks_like_mp4(first_bytes):
        raise HTTPException(status_code=415, detail=NOT_AN_MP4)

    # 3. Save it with the real size: moderation "pending", lifecycle "loaded" (not shown yet).
    video = repo.add_video(session, user.id, data.object_key, data.duration_sec, size)
    try:
        await session.commit()
    except IntegrityError:  # object_key is unique: this file was confirmed before
        await session.rollback()
        raise HTTPException(status_code=409, detail=ALREADY_CONFIRMED) from None

    # 4. Queue the moderation, after the answer has gone out, so the user never waits for it.
    background.add_task(queue.moderate_video, video.id, video.object_key)
    return video


async def list_my_videos(
    session: AsyncSession, storage: Storage, user: User, expires_sec: int
) -> MyVideosOut:
    """My videos that are not deleted, each with a signed link to watch it."""
    videos = await repo.list_my_videos(session, user.id)
    expires = timedelta(seconds=expires_sec)
    return MyVideosOut(
        items=[
            MyVideoOut(
                id=video.id,
                object_key=video.object_key,
                duration_sec=video.duration_sec,
                size_bytes=video.size_bytes,
                content_type=video.content_type,
                moderation_status=video.moderation_status,
                lifecycle_status=video.lifecycle_status,
                created_at=video.created_at,
                updated_at=video.updated_at,
                signed_url=storage.download_url(video.object_key, expires),
                expires_sec=expires_sec,
            )
            for video in videos
        ]
    )


async def find_my_video(session: AsyncSession, user: User, video_id: int) -> IntroVideo:
    """One of my videos, or 404. Someone else's video gets the same 404 as a missing one, so
    nobody learns which ids exist; a deleted video is gone for good."""
    video = await repo.get_my_video(session, user.id, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=VIDEO_NOT_FOUND)
    return video


async def post_video(session: AsyncSession, user: User, video_id: int) -> IntroVideo:
    """Show this video in the feed. Only an approved one; my previous posted video is unposted."""
    video = await find_my_video(session, user, video_id)
    if video.moderation_status != "approved":
        raise HTTPException(status_code=409, detail=NOT_APPROVED)
    if video.lifecycle_status == "posted":
        raise HTTPException(status_code=409, detail=ALREADY_POSTED)
    # One posted video per user: the database refuses a second one (a unique index on the
    # posted videos, BE-02), so the old one is unposted first, then this one is posted.
    await repo.unpost_posted_video(session, user.id)
    video.lifecycle_status = "posted"
    await session.commit()
    return video


async def unpost_video(session: AsyncSession, user: User, video_id: int) -> IntroVideo:
    """Take my posted video out of the feed. I can post it again later."""
    video = await find_my_video(session, user, video_id)
    if video.lifecycle_status != "posted":
        raise HTTPException(status_code=409, detail=NOT_POSTED)
    video.lifecycle_status = "unposted"
    await session.commit()
    return video


async def delete_video(session: AsyncSession, user: User, video_id: int) -> IntroVideo:
    """Soft delete: the row stays (with its file), only its lifecycle becomes "deleted". It
    leaves my list and the feed, no longer counts in my 3 videos, and cannot come back."""
    video = await find_my_video(session, user, video_id)
    video.lifecycle_status = "deleted"
    await session.commit()
    return video
