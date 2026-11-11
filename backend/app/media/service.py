"""The rules of intro videos, avatars and company logos. Routes call these functions; these
call the repo and storage."""

import asyncio
import re
from datetime import timedelta
from uuid import uuid4

import structlog
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.core.queue import TaskQueue
from app.core.storage import Storage
from app.media import repo
from app.media.constants import (
    AVATARS_FOLDER,
    JPEG_SIGNATURE,
    LOGOS_FOLDER,
    MAX_ACTIVE_VIDEOS,
    MAX_PICTURE_BYTES,
    MAX_SIZE_BYTES,
    MP4_CONTENT_TYPE,
    MP4_EXTENSION,
    MP4_SIGNATURE,
    MP4_SIGNATURE_END,
    MP4_SIGNATURE_START,
    PICTURE_SIGNATURE_BYTES,
    PICTURE_TYPES,
    PNG_SIGNATURE,
    UUID_PATTERN,
    WEBP_SIGNATURE_RIFF,
    WEBP_SIGNATURE_WEBP,
)
from app.media.models import IntroVideo
from app.media.schemas import (
    ConfirmIn,
    FeedOut,
    FeedVideoOut,
    MyVideoOut,
    MyVideosOut,
    PictureUploadUrlOut,
    UploadUrlIn,
    UploadUrlOut,
)
from app.users.models import User

log = structlog.get_logger(__name__)

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
ONLY_PICTURES = "Only jpg, png or webp pictures are accepted"
NO_PICTURE = "No uploaded file at this object_key: PUT the picture to put_url first"
PICTURE_TOO_BIG = f"The picture is larger than {MAX_PICTURE_BYTES // (1024 * 1024)} MiB"
WRONG_CONTENT_TYPE = "Upload the picture with the header Content-Type: {}"
NOT_THAT_PICTURE = "The uploaded file is not a {} picture"
NO_COMPANY = "You have no company"


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
    first_bytes = b""
    if size >= MP4_SIGNATURE_END:  # a shorter file cannot be an MP4, and has nothing to read
        first_bytes = await asyncio.to_thread(
            storage.first_bytes, data.object_key, MP4_SIGNATURE_END
        )
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
        after = (await repo.feed_group_of(session, cursor, job_id), cursor)
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


# --- Avatars and company logos (BE-08) -----------------------------------------------------


def create_picture_upload_url(
    storage: Storage, folder: str, owner_id: int, ext: str, expires_sec: int
) -> PictureUploadUrlOut:
    """A new key in the owner's public folder (avatars/<user id>/ or logos/<company id>/) and
    a signed link to PUT one jpg, png or webp picture there (415 for anything else)."""
    ext = ext.lower()  # "PNG" is fine too; the key is always written in small letters
    if ext not in PICTURE_TYPES:
        raise HTTPException(status_code=415, detail=ONLY_PICTURES)
    object_key = f"{folder}/{owner_id}/{uuid4()}.{ext}"
    return PictureUploadUrlOut(
        object_key=object_key,
        put_url=storage.upload_url(object_key, timedelta(seconds=expires_sec)),
        expires_sec=expires_sec,
        max_bytes=MAX_PICTURE_BYTES,
    )


def looks_like_picture(ext: str, first_bytes: bytes) -> bool:
    """True when the file really starts like a picture of this type, whatever its name says."""
    if ext == "jpg":
        return first_bytes.startswith(JPEG_SIGNATURE)
    if ext == "png":
        return first_bytes.startswith(PNG_SIGNATURE)
    if ext == "webp":
        return first_bytes[0:4] == WEBP_SIGNATURE_RIFF and first_bytes[8:12] == WEBP_SIGNATURE_WEBP
    return False


async def check_picture(storage: Storage, folder: str, owner_id: int, object_key: str) -> None:
    """Refuse the key unless upload-url could have made it for this owner, and the file unless
    it really is a small enough picture of the key's type."""
    # 1. The key. Its extension must be jpg, png or webp...
    ext = object_key.rsplit(".", 1)[-1]
    if ext not in PICTURE_TYPES:
        raise HTTPException(status_code=415, detail=ONLY_PICTURES)
    # ...and the whole key must be <folder>/<owner id>/<uuid>.<ext>: nobody can confirm a file
    # of another user or company, or a path trick such as "avatars/1/../2/...".
    if re.fullmatch(rf"{folder}/{owner_id}/{UUID_PATTERN}\.{ext}", object_key) is None:
        raise HTTPException(status_code=400, detail=NOT_YOUR_KEY)

    # 2. The file in storage itself (stat_object), not what the browser says about it. The
    # MinIO calls wait for the network, so they run in a worker thread.
    stored = await asyncio.to_thread(storage.stat, object_key)
    if stored is None:  # never uploaded, or uploaded somewhere else
        raise HTTPException(status_code=400, detail=NO_PICTURE)
    if stored.size > MAX_PICTURE_BYTES:
        raise HTTPException(status_code=413, detail=PICTURE_TOO_BIG)
    # MinIO sends this Content-Type back to everyone who downloads the file: it must be the
    # picture's own type, never something a browser would run, such as text/html.
    if stored.content_type != PICTURE_TYPES[ext]:
        raise HTTPException(status_code=415, detail=WRONG_CONTENT_TYPE.format(PICTURE_TYPES[ext]))
    first_bytes = b""
    if stored.size >= PICTURE_SIGNATURE_BYTES:  # a smaller file cannot be a picture
        first_bytes = await asyncio.to_thread(
            storage.first_bytes, object_key, PICTURE_SIGNATURE_BYTES
        )
    if not looks_like_picture(ext, first_bytes):
        raise HTTPException(status_code=415, detail=NOT_THAT_PICTURE.format(ext))


async def remove_files(storage: Storage, keys: list[str]) -> None:
    """Delete files that nothing points to any more. The database is already saved, so if
    MinIO fails here the request still succeeds: the file left behind is logged instead."""
    for key in keys:
        try:
            await asyncio.to_thread(storage.remove, key)
        except Exception:  # MinIO down or unreachable: log it with the traceback
            log.exception("file not removed from storage", object_key=key)


async def confirm_avatar(session: AsyncSession, storage: Storage, user: User, key: str) -> None:
    """Make the checked picture my avatar. The file of my old avatar is deleted: its public
    link must not keep working once I have changed my picture."""
    await check_picture(storage, AVATARS_FOLDER, user.id, key)
    old_key = user.avatar_object_key
    user.avatar_object_key = key
    await session.commit()  # the new avatar is saved first, then the old file goes
    if old_key and old_key != key:
        await remove_files(storage, [old_key])


async def find_my_company(session: AsyncSession, user: User) -> Company:
    """My company that is not deleted, or 404: only an employer has a logo."""
    company = await repo.get_active_company(session, user.id)
    if company is None:
        raise HTTPException(status_code=404, detail=NO_COMPANY)
    return company


async def create_logo_upload_url(
    session: AsyncSession, storage: Storage, user: User, ext: str, expires_sec: int
) -> PictureUploadUrlOut:
    """Like the avatar's, in my company's folder: logos/<company id>/<uuid>.<ext>."""
    company = await find_my_company(session, user)
    return create_picture_upload_url(storage, LOGOS_FOLDER, company.id, ext, expires_sec)


async def confirm_logo(session: AsyncSession, storage: Storage, user: User, key: str) -> None:
    """Make the checked picture my company's logo; the file of the old logo is deleted."""
    company = await find_my_company(session, user)
    await check_picture(storage, LOGOS_FOLDER, company.id, key)
    old_key = company.logo_object_key
    company.logo_object_key = key
    company.updated_by_id = user.id  # who last changed the company (AuditMixin, BE-02)
    await session.commit()
    if old_key and old_key != key:
        await remove_files(storage, [old_key])


async def forget_pictures(session: AsyncSession, user: User) -> list[str]:
    """For an account being deleted: empty its avatar and its company's logo (saved with the
    caller's commit). Returns the keys of their files, for remove_files once that is saved."""
    keys = [user.avatar_object_key]
    user.avatar_object_key = None
    company = await repo.get_active_company(session, user.id)
    if company is not None:
        # Nobody can change or remove this logo any more once its only owner is gone.
        keys.append(company.logo_object_key)
        company.logo_object_key = None
    return [key for key in keys if key]
