"""The rules of intro videos, avatars and company logos. Routes call these functions; these
call the repo and storage."""

import asyncio
import io
import re
from datetime import timedelta
from uuid import uuid4

from fastapi import BackgroundTasks, HTTPException
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import unauthorized
from app.auth.service import INVALID_TOKEN
from app.companies import service as companies
from app.companies.models import Company
from app.core.queue import TaskQueue
from app.core.storage import Storage, remove_files
from app.media import repo
from app.media.constants import (
    AVATARS_FOLDER,
    LOGOS_FOLDER,
    MAX_ACTIVE_VIDEOS,
    MAX_PICTURE_BYTES,
    MAX_PICTURE_PIXELS,
    MAX_SIZE_BYTES,
    MP4_CONTENT_TYPE,
    MP4_EXTENSION,
    MP4_SIGNATURE,
    MP4_SIGNATURE_END,
    MP4_SIGNATURE_START,
    PICTURE_FORMATS,
    PICTURE_TYPES,
    ROW_LOCK,
    STAGING_FOLDER,
    UUID_PATTERN,
    VIDEOS_FOLDER,
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
ONLY_PICTURES = "Only jpg, png or webp pictures are accepted"
NO_PICTURE = "No uploaded file at this object_key: PUT the picture to put_url first"
PICTURE_TOO_BIG = f"The picture is larger than {MAX_PICTURE_BYTES // (1024 * 1024)} MiB"
NOT_THAT_PICTURE = "The uploaded file is not a {} picture"
TOO_MANY_PIXELS = f"The picture has more than {MAX_PICTURE_PIXELS // 1_000_000} million pixels"
NO_COMPANY = "You have no company"


def object_key_for(user_id: int) -> str:
    """A new, unguessable place for the upload of one of this user's videos."""
    return f"users/{user_id}/intro/{uuid4()}.{MP4_EXTENSION}"


def video_key_for(user_id: int) -> str:
    """A new place for the copy that confirm keeps of one of this user's videos:
    videos/<user id>/<uuid>.mp4. No upload link ever points there."""
    return f"{VIDEOS_FOLDER}/{user_id}/{uuid4()}.{MP4_EXTENSION}"


def is_my_object_key(user_id: int, object_key: str) -> bool:
    """True only for a key upload-url could have made for this user. fullmatch: the whole key
    must fit the pattern, so "users/1/intro/../2/..." or a key of another user never does,
    and neither does a confirmed video's own key (videos/...)."""
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
    """Copy the uploaded file to a key of the server's own and delete the upload, check the
    copy, save the video as pending with the copy's key, and queue its moderation."""
    # 1. The key must be one of mine: nobody can confirm another user's file.
    if not is_my_object_key(user.id, data.object_key):
        raise HTTPException(status_code=400, detail=NOT_YOUR_KEY)
    # A video confirmed before confirm made copies kept its upload key as its object_key.
    # Step 2 would copy that file and then delete it, so the video would lose its file.
    if await repo.has_video_at(session, data.object_key):
        raise HTTPException(status_code=409, detail=ALREADY_CONFIRMED)

    # 2. Copy the upload to a new key that no upload link points at, then delete the upload.
    # put_url works until it expires, so another file can still be PUT at the upload key;
    # but from now on nothing reads it. The video that is checked, moderated and shown is
    # the copy, and only the server writes there. MinIO makes the copy itself. The MinIO
    # calls wait for the network, so they run in a worker thread.
    video_key = video_key_for(user.id)
    try:
        copied = await asyncio.to_thread(storage.copy, data.object_key, video_key, MP4_CONTENT_TYPE)
    finally:
        await remove_files(storage, [data.object_key])  # also when the copy failed
    if not copied:  # never uploaded, uploaded somewhere else, or confirmed already
        raise HTTPException(status_code=400, detail=NO_FILE)

    try:
        # 3. Look at the copy instead of trusting what the browser says about it: these
        # are the very bytes the feed will show and the moderation will check.
        size = await asyncio.to_thread(storage.size, video_key)
        if size > MAX_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=TOO_BIG)
        first_bytes = b""
        if size >= MP4_SIGNATURE_END:  # a shorter file cannot be an MP4, and has nothing to read
            first_bytes = await asyncio.to_thread(storage.first_bytes, video_key, MP4_SIGNATURE_END)
        if not looks_like_mp4(first_bytes):
            raise HTTPException(status_code=415, detail=NOT_AN_MP4)

        # 4. At most 3 videos. Two confirms of mine at the same time must not both count 2
        # and both save: so I lock my row in users first. The second confirm waits at the
        # lock until the first is saved (commit), then counts 3 and gets 409. Other users
        # never wait.
        await repo.lock_user(session, user.id)
        if await repo.count_active_videos(session, user.id) >= MAX_ACTIVE_VIDEOS:
            raise HTTPException(status_code=409, detail=TOO_MANY_VIDEOS)

        # 5. Save it with the copy's key and real size: moderation "pending", lifecycle
        # "loaded" (not shown yet). The commit also lets go of the lock.
        video = repo.add_video(session, user.id, video_key, data.duration_sec, size)
        await session.commit()
    except Exception:
        # Refused, or not saved: nothing will ever read the copy, so it goes too.
        await remove_files(storage, [video_key])
        raise

    # 6. Queue the moderation, after the answer has gone out, so the user never waits for it.
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


# --- Avatars and company logos (BE-08) -----------------------------------------------------


def create_picture_upload_url(
    storage: Storage, folder: str, owner_id: int, ext: str, expires_sec: int
) -> PictureUploadUrlOut:
    """A new key in the owner's private staging folder (staging/avatars/<user id>/ or
    staging/logos/<company id>/) and a signed link to PUT one jpg, png or webp picture there
    (415 for anything else). Nobody can download from staging/: the picture becomes public only
    when confirm has checked it and the server has copied it into the public folder."""
    ext = ext.lower()  # "PNG" is fine too; the key is always written in small letters
    if ext not in PICTURE_TYPES:
        raise HTTPException(status_code=415, detail=ONLY_PICTURES)
    object_key = f"{STAGING_FOLDER}/{folder}/{owner_id}/{uuid4()}.{ext}"
    return PictureUploadUrlOut(
        object_key=object_key,
        put_url=storage.upload_url(object_key, timedelta(seconds=expires_sec)),
        expires_sec=expires_sec,
        max_bytes=MAX_PICTURE_BYTES,
    )


def is_my_staging_key(folder: str, owner_id: int, key: str) -> bool:
    """True only for a key upload-url could have made for this owner:
    staging/<folder>/<owner id>/<uuid>.<jpg, png or webp>. fullmatch: the whole key must fit, so
    a file of another user or company, a public file, or a path trick such as "../" never does."""
    extensions = "|".join(PICTURE_TYPES)
    pattern = rf"{STAGING_FOLDER}/{folder}/{owner_id}/{UUID_PATTERN}\.({extensions})"
    return re.fullmatch(pattern, key) is not None


async def discard_upload(storage: Storage, folder: str, owner_id: int, staging_key: str) -> None:
    """Delete an upload that will never be published. Only one in the owner's own staging
    folder: the key comes from the request, so it could name anybody's file."""
    if is_my_staging_key(folder, owner_id, staging_key):
        await remove_files(storage, [staging_key])


def check_picture_file(ext: str, data: bytes) -> None:
    """Refuse the file unless it really is a picture of this type. Pillow recognises the type
    from the first bytes, whatever the file is called, then decodes every pixel: a file that
    only starts like a picture, or is cut short, fails. CPU work: run it in a worker thread."""
    try:
        with Image.open(io.BytesIO(data), formats=[PICTURE_FORMATS[ext]]) as picture:
            # The size in pixels is at the start of the file: a huge picture is refused before
            # it is decoded.
            too_big = picture.width * picture.height > MAX_PICTURE_PIXELS
            if not too_big:
                picture.load()  # decodes every pixel
    except Image.DecompressionBombError:  # Pillow's own limit, far above ours
        too_big = True
    except Exception:  # Pillow raises several kinds of errors for a file it cannot read
        raise HTTPException(status_code=415, detail=NOT_THAT_PICTURE.format(ext)) from None
    if too_big:
        raise HTTPException(status_code=413, detail=TOO_MANY_PIXELS)


async def publish_picture(storage: Storage, folder: str, owner_id: int, staging_key: str) -> str:
    """Check the picture uploaded at staging_key and publish it: the server writes a copy of it
    at a new key, <folder>/<owner id>/<new uuid>.<ext>, which anyone may download, and returns
    that key. The uploaded file is deleted, whether it is accepted or refused."""
    # 1. The key. Its extension must be jpg, png or webp...
    ext = staging_key.rsplit(".", 1)[-1]
    if ext not in PICTURE_TYPES:
        raise HTTPException(status_code=415, detail=ONLY_PICTURES)
    # ...and the whole key one that upload-url made for this owner: nobody can confirm a file of
    # another user or company, a public file, or a path trick such as "../".
    if not is_my_staging_key(folder, owner_id, staging_key):
        raise HTTPException(status_code=400, detail=NOT_YOUR_KEY)

    # 2. The file in storage itself (stat_object), not what the browser says about it. The
    # MinIO calls wait for the network, so they run in a worker thread.
    stored = await asyncio.to_thread(storage.stat, staging_key)
    if stored is None:  # never uploaded, uploaded somewhere else, or already confirmed
        raise HTTPException(status_code=400, detail=NO_PICTURE)
    try:
        if stored.size > MAX_PICTURE_BYTES:
            raise HTTPException(status_code=413, detail=PICTURE_TOO_BIG)
        # 3. Read the file once and check those very bytes: they are the ones published, even
        # if the upload link is used again meanwhile. At most the limit + 1 byte, so a file
        # made bigger since stat is refused without being read whole.
        data = await asyncio.to_thread(storage.read, staging_key, MAX_PICTURE_BYTES + 1)
        data = data or b""  # None: the file is gone since stat
        if len(data) > MAX_PICTURE_BYTES:
            raise HTTPException(status_code=413, detail=PICTURE_TOO_BIG)
        await asyncio.to_thread(check_picture_file, ext, data)
    finally:
        # 4. The uploaded file is never needed again, refused or accepted. Deleting it now also
        # means the same upload cannot be confirmed, and published, a second time.
        await remove_files(storage, [staging_key])

    # 5. The public copy: written by the server, at a new key that no upload link has ever
    # pointed at, with the Content-Type of the type it checked (never the uploader's).
    public_key = f"{folder}/{owner_id}/{uuid4()}.{ext}"
    await asyncio.to_thread(storage.put, public_key, data, PICTURE_TYPES[ext])
    return public_key


async def lock_my_account(session: AsyncSession, user: User) -> bool:
    """Lock my row until the commit (ROW_LOCK), read it again, and say whether my account is
    still active. The picture confirms and the account deletion all take this lock, so for
    one account they run one after the other, and the second sees what the first saved:
    a second confirm of the same upload finds it already gone, a confirm after the deletion
    finds the account deleted. Like the video limit's lock (repo.lock_user), but refresh also
    reads the row again (status, avatar_object_key) instead of trusting the earlier read."""
    await session.refresh(user, with_for_update=ROW_LOCK)
    return user.status == "active"


async def confirm_avatar(
    session: AsyncSession, storage: Storage, user: User, staging_key: str
) -> None:
    """Publish the checked picture as my avatar. The file of my old avatar is deleted: its
    public link must not keep working once I have changed my picture."""
    # The sign-in check passed when the request came in, but my account may have been deleted
    # while this request waited. A deleted account gets nothing published, and the same 401 as
    # on any request; its upload is deleted, as on any refusal.
    if not await lock_my_account(session, user):
        await discard_upload(storage, AVATARS_FOLDER, user.id, staging_key)
        raise unauthorized(INVALID_TOKEN)
    new_key = await publish_picture(storage, AVATARS_FOLDER, user.id, staging_key)
    old_key = user.avatar_object_key
    user.avatar_object_key = new_key
    await session.commit()  # the new avatar is saved first, then the old file goes
    if old_key:
        await remove_files(storage, [old_key])


async def find_my_company(session: AsyncSession, user: User) -> Company:
    """My company that is not deleted (BE-21 finds it), or 404: only an employer has a logo."""
    company = await companies.get_my_company(session, user.id)
    if company is None:
        raise HTTPException(status_code=404, detail=NO_COMPANY)
    return company


async def create_logo_upload_url(
    session: AsyncSession, storage: Storage, user: User, ext: str, expires_sec: int
) -> PictureUploadUrlOut:
    """Like the avatar's, in my company's staging folder: staging/logos/<company id>/."""
    company = await find_my_company(session, user)
    return create_picture_upload_url(storage, LOGOS_FOLDER, company.id, ext, expires_sec)


async def confirm_logo(
    session: AsyncSession, storage: Storage, user: User, staging_key: str
) -> None:
    """Publish the checked picture as my company's logo; the file of the old logo is deleted."""
    company = await find_my_company(session, user)
    # Two locks, always in this order, as the account deletion takes them: my row, then my
    # company's. (Two requests that each held one and waited for the other would wait forever.)
    # My account first, like the avatar: deleting my account empties the logo too.
    if not await lock_my_account(session, user):
        await discard_upload(storage, LOGOS_FOLDER, company.id, staging_key)
        raise unauthorized(INVALID_TOKEN)
    # Then my company's row, read again: DELETE /companies takes this lock too, so a company
    # deleted while this request waited is seen here, and gets the usual 404.
    await session.refresh(company, with_for_update=ROW_LOCK)
    if company.status != "active" or company.owner_user_id != user.id:
        await discard_upload(storage, LOGOS_FOLDER, company.id, staging_key)
        raise HTTPException(status_code=404, detail=NO_COMPANY)
    new_key = await publish_picture(storage, LOGOS_FOLDER, company.id, staging_key)
    old_key = company.logo_object_key
    company.logo_object_key = new_key
    company.updated_by_id = user.id  # who last changed the company (AuditMixin, BE-02)
    await session.commit()
    if old_key:
        await remove_files(storage, [old_key])


async def forget_pictures(session: AsyncSession, user: User) -> list[str]:
    """For an account being deleted: empty its avatar and its company's logo (saved with the
    caller's commit). Returns the keys of their files, for remove_files once that is saved.

    It locks my row, then my company's, until that commit: the locks of the picture confirms,
    in the same order. Each row is read again before its key: a confirm that came first has
    saved its new picture, which is then the file deleted; one that comes later waits, then
    finds my account deleted and is refused."""
    await session.refresh(user, with_for_update=ROW_LOCK)  # the lock of lock_my_account
    keys = [user.avatar_object_key]
    user.avatar_object_key = None
    company = await companies.get_my_company(session, user.id)
    if company is not None:
        await session.refresh(company, with_for_update=ROW_LOCK)
        # Nobody can change or remove this logo any more once its only owner is gone.
        keys.append(company.logo_object_key)
        company.logo_object_key = None
    return [key for key in keys if key]
