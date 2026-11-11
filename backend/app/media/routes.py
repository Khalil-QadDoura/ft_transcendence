"""The /api/media endpoints. Each one needs the logged-in user (CurrentUser)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.queue import TaskQueue, get_queue
from app.core.storage import Storage, get_storage
from app.db.session import get_session
from app.media import service
from app.media.schemas import ConfirmIn, UploadUrlIn, UploadUrlOut, VideoStatusOut

router = APIRouter(prefix="/media", tags=["media"])  # mounted under /api

Session = Annotated[AsyncSession, Depends(get_session)]
Files = Annotated[Storage, Depends(get_storage)]
Queue = Annotated[TaskQueue, Depends(get_queue)]


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
