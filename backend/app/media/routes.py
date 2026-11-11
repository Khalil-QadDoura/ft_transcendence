"""The /api/media endpoints. Each one needs the logged-in user (CurrentUser), except the
default avatar picture."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.queue import TaskQueue, get_queue
from app.core.storage import Storage, get_storage
from app.db.session import get_session
from app.media import service
from app.media.constants import (
    AVATARS_FOLDER,
    DEFAULT_PICTURE_EXTENSION,
    FEED_DEFAULT_LIMIT,
    FEED_MAX_LIMIT,
    MAX_URL_EXPIRES_SEC,
    MIN_URL_EXPIRES_SEC,
    UPLOAD_URL_EXPIRES_SEC,
    VIEW_URL_EXPIRES_SEC,
)
from app.media.schemas import (
    ConfirmIn,
    FeedOut,
    MyVideosOut,
    PictureConfirmIn,
    PictureUploadUrlOut,
    UploadUrlIn,
    UploadUrlOut,
    VideoStatusOut,
)

router = APIRouter(prefix="/media", tags=["media"])  # mounted under /api

Session = Annotated[AsyncSession, Depends(get_session)]
Files = Annotated[Storage, Depends(get_storage)]
Queue = Annotated[TaskQueue, Depends(get_queue)]
# How long a signed link works: ?expires_sec=60 to 3600 (by default 300 to watch a video,
# 900 to upload a picture).
ExpiresSec = Annotated[int, Query(ge=MIN_URL_EXPIRES_SEC, le=MAX_URL_EXPIRES_SEC)]

# The picture of users who have none (DEFAULT_AVATAR_URL points here): a grey head and
# shoulders, read once when the app starts.
DEFAULT_AVATAR = (Path(__file__).parent / "default-avatar.svg").read_bytes()
# Browsers may keep it for a day instead of asking again for every avatar on a page.
DEFAULT_AVATAR_CACHE = "public, max-age=86400"


@router.post("/intro-video/upload-url")
async def get_upload_url(user: CurrentUser, data: UploadUrlIn, storage: Files) -> UploadUrlOut:
    """Step 1 of 3: a signed link to PUT one MP4 straight into storage (415 for anything else)."""
    return service.create_upload_url(storage, user, data)


@router.post("/intro-video/confirm", status_code=201)
async def confirm_upload(
    user: CurrentUser,
    data: ConfirmIn,
    session: Session,
    storage: Files,
    queue: Queue,
    background: BackgroundTasks,
) -> VideoStatusOut:
    """Step 3 of 3, after the PUT: check the file, save the video, queue its moderation."""
    video = await service.confirm_upload(session, storage, queue, background, user, data)
    return VideoStatusOut.model_validate(video)


@router.get("/intro-video/mine")
async def list_my_videos(
    user: CurrentUser,
    session: Session,
    storage: Files,
    expires_sec: ExpiresSec = VIEW_URL_EXPIRES_SEC,
) -> MyVideosOut:
    """My videos (not the deleted ones), newest first. Poll it while one is "pending"."""
    return await service.list_my_videos(session, storage, user, expires_sec)


@router.post("/intro-video/{video_id}/post")
async def post_video(user: CurrentUser, video_id: int, session: Session) -> VideoStatusOut:
    """Show this approved video in the feed; my previous posted video becomes "unposted"."""
    return VideoStatusOut.model_validate(await service.post_video(session, user, video_id))


@router.post("/intro-video/{video_id}/unpost")
async def unpost_video(user: CurrentUser, video_id: int, session: Session) -> VideoStatusOut:
    """Take my posted video out of the feed."""
    return VideoStatusOut.model_validate(await service.unpost_video(session, user, video_id))


@router.post("/intro-video/{video_id}/delete")
async def delete_video(user: CurrentUser, video_id: int, session: Session) -> VideoStatusOut:
    """Delete my video (a soft delete): the row stays, marked "deleted"."""
    return VideoStatusOut.model_validate(await service.delete_video(session, user, video_id))


@router.get("/feed")
async def get_feed(
    user: CurrentUser,
    session: Session,
    storage: Files,
    limit: Annotated[int, Query(ge=1, le=FEED_MAX_LIMIT)] = FEED_DEFAULT_LIMIT,
    cursor: int | None = None,
    job_id: int | None = None,
    expires_sec: ExpiresSec = VIEW_URL_EXPIRES_SEC,
) -> FeedOut:
    """The posted videos. ?cursor=<next_cursor> gives the next page; ?job_id= orders it for
    that job (its applicants first, then matching positions)."""
    return await service.get_feed(session, storage, user, limit, cursor, job_id, expires_sec)


@router.get("/avatar/default.svg", response_class=Response)
async def get_default_avatar() -> Response:
    """The default avatar picture. No login: it is an <img> on every page, like the avatars."""
    return Response(
        DEFAULT_AVATAR, media_type="image/svg+xml", headers={"Cache-Control": DEFAULT_AVATAR_CACHE}
    )


@router.post("/avatar/upload-url")
async def get_avatar_upload_url(
    user: CurrentUser,
    storage: Files,
    ext: str = DEFAULT_PICTURE_EXTENSION,
    expires_sec: ExpiresSec = UPLOAD_URL_EXPIRES_SEC,
) -> PictureUploadUrlOut:
    """Step 1 of 3: a signed link to PUT my new picture (?ext=jpg, png or webp; 415 for
    anything else) straight into storage, under avatars/<my id>/."""
    return service.create_picture_upload_url(storage, AVATARS_FOLDER, user.id, ext, expires_sec)


@router.post("/avatar/confirm", status_code=204)
async def confirm_avatar(
    user: CurrentUser, data: PictureConfirmIn, session: Session, storage: Files
) -> None:
    """Step 3 of 3, after the PUT: check the picture and make it my avatar (the old file is
    deleted). GET /api/users/me then gives its avatar_url."""
    await service.confirm_avatar(session, storage, user, data.object_key)


@router.post("/company-logo/upload-url")
async def get_logo_upload_url(
    user: CurrentUser,
    session: Session,
    storage: Files,
    ext: str = DEFAULT_PICTURE_EXTENSION,
    expires_sec: ExpiresSec = UPLOAD_URL_EXPIRES_SEC,
) -> PictureUploadUrlOut:
    """Like the avatar's, for my company's logo: employers only (404 without a company)."""
    return await service.create_logo_upload_url(session, storage, user, ext, expires_sec)


@router.post("/company-logo/confirm", status_code=204)
async def confirm_logo(
    user: CurrentUser, data: PictureConfirmIn, session: Session, storage: Files
) -> None:
    """Check the picture and make it my company's logo (the old file is deleted)."""
    await service.confirm_logo(session, storage, user, data.object_key)
