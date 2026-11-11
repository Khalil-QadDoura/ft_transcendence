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
from app.media.schemas import (
    ConfirmIn,
    FeedOut,
    FeedVideoOut,
    MyVideoOut,
    MyVideosOut,
    UploadUrlIn,
    UploadUrlOut,
)
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
# Written like the other 422s of the API ("<where> → <field>: <message>").
UNKNOWN_CURSOR = "query → cursor: No video has this id: use the next_cursor of the page before"


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

    # 2. Look at the file in storage instead of trusting what the browser says about it.
    # The MinIO calls wait for the network, so they run in a worker thread.
    size = await asyncio.to_thread(storage.size, data.object_key)
    if size is None:  # never uploaded, or uploaded somewhere else
        raise HTTPException(status_code=400, detail=NO_FILE)
    if size > MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=TOO_BIG)
    first_bytes = b""
    if size >= MP4_SIGNATURE_END:  # a shorter file cannot be an MP4, and has nothing to read
        first_bytes = await asyncio.to_thread(
            storage.first_bytes, data.object_key, MP4_SIGNATURE_END
        )
    if not looks_like_mp4(first_bytes):
        raise HTTPException(status_code=415, detail=NOT_AN_MP4)

    # 3. At most 3 videos. Two confirms of mine at the same time must not both count 2 and
    # both save: so I lock my row in users first. The second confirm waits at the lock until
    # the first is saved (commit), then counts 3 and gets 409. Other users never wait.
    await repo.lock_user(session, user.id)
    if await repo.count_active_videos(session, user.id) >= MAX_ACTIVE_VIDEOS:
        raise HTTPException(status_code=409, detail=TOO_MANY_VIDEOS)

    # 4. Save it with the real size: moderation "pending", lifecycle "loaded" (not shown yet).
    # The commit also lets go of the lock.
    video = repo.add_video(session, user.id, data.object_key, data.duration_sec, size)
    try:
        await session.commit()
    except IntegrityError:  # object_key is unique: this file was confirmed before
        await session.rollback()
        raise HTTPException(status_code=409, detail=ALREADY_CONFIRMED) from None

    # 5. Queue the moderation, after the answer has gone out, so the user never waits for it.
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
    """One of my videos, or 404, for post, unpost or delete. Someone else's video gets the
    same 404 as a missing one, so nobody learns which ids exist; a deleted video is gone for good.

    First I lock my row in users, the lock confirm takes: post, unpost and delete of my videos
    wait in line, one at a time, until the one before has saved (commit). Only then is the
    video read, fresh from the database: a video another request deleted meanwhile is 404,
    so post or unpost can never bring it back."""
    await repo.lock_user(session, user.id)
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


def author_name(first_name: str | None, last_name: str | None) -> str | None:
    """The name to show, e.g. "Ana Silva" or "Ana"; None when the profile has no name yet."""
    return " ".join(name for name in (first_name, last_name) if name) or None


async def get_feed(
    session: AsyncSession,
    storage: Storage,
    user: User,
    limit: int,
    cursor: int | None,
    job_id: int | None,
    expires_sec: int,
) -> FeedOut:
    """One page of the feed. With job_id, that job's waiting applicants come first, then the
    candidates whose position matches its title, then everyone else (newest first in each)."""
    employer = await repo.owns_active_company(session, user.id)
    # cursor = the id of the last video of the page before. The page goes on after it, so we
    # need its group too: by id alone, a page would skip the newer videos of later groups.
    after = None
    if cursor is not None:
        group = await repo.feed_group_of(session, cursor, job_id)
        # No video has this id, so it is no next_cursor of ours. A video that has only left
        # the feed since (unposted, deleted) still has its row, so its next page still comes.
        if group is None:
            raise HTTPException(status_code=422, detail=UNKNOWN_CURSOR)
        after = (group, cursor)
    # One video more than asked for, only to know whether there is a next page.
    rows = await repo.list_feed(session, job_id, employer, after, limit + 1)
    page = rows[:limit]
    expires = timedelta(seconds=expires_sec)
    items = [
        FeedVideoOut(
            id=video.id,
            user_id=video.user_id,
            duration_sec=video.duration_sec,
            size_bytes=video.size_bytes,
            content_type=video.content_type,
            signed_url=storage.download_url(video.object_key, expires),
            expires_sec=expires_sec,
            created_at=video.created_at,
            author_name=author_name(first_name, last_name),
            author_position=position,
        )
        for video, first_name, last_name, position in page
    ]
    next_cursor = items[-1].id if len(rows) > limit else None
    return FeedOut(items=items, next_cursor=next_cursor)
