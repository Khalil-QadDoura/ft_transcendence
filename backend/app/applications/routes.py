"""HTTP endpoints for applications, status transitions, and job page views (BE-28)."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications import service
from app.applications.constants import DEFAULT_PAGE_LIMIT, MAX_ID, MAX_PAGE_LIMIT
from app.applications.schemas import (
    ApplicationOut,
    ApplicationsPage,
    ApplicationStatus,
    ApplyRequest,
    StatusUpdateRequest,
)
from app.auth.deps import CurrentUser, OptionalUser
from app.core.limiter import client_ip
from app.core.redis_client import get_redis
from app.core.storage import Storage, get_storage
from app.db.session import get_session

router = APIRouter(tags=["applications"])

Session = Annotated[AsyncSession, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]
Files = Annotated[Storage, Depends(get_storage)]
EntityId = Annotated[int, Path(ge=1, le=MAX_ID)]
CursorParam = Annotated[int | None, Query(ge=1, le=MAX_ID)]
LimitParam = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
StatusFilterParam = Annotated[ApplicationStatus | None, Query(alias="status")]


@router.post(
    "/jobs/{job_id}/apply",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
)
async def apply_to_job(
    job_id: EntityId,
    session: Session,
    redis: RedisClient,
    storage: Files,
    user: CurrentUser,
    body: Annotated[ApplyRequest | None, Body()] = None,
) -> ApplicationOut:
    """Apply to an open job with the caller's posted approved intro video."""
    return await service.apply(
        session,
        redis,
        storage,
        job_id=job_id,
        applicant=user,
        cover_note=body.cover_note if body is not None else None,
    )


@router.post("/jobs/{job_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def record_job_view(
    job_id: EntityId,
    request: Request,
    session: Session,
    redis: RedisClient,
    viewer: OptionalUser,
) -> None:
    """Record a unique view for an open job (deduplicated per viewer per 24 hours)."""
    ip = client_ip(request)
    await service.record_job_view(
        session,
        redis,
        job_id=job_id,
        viewer_id=viewer.id if viewer else None,
        client_ip=ip,
    )


@router.get("/jobs/{job_id}/applications", response_model=ApplicationsPage)
async def list_job_applications(
    job_id: EntityId,
    session: Session,
    storage: Files,
    user: CurrentUser,
    status_filter: StatusFilterParam = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_LIMIT,
) -> ApplicationsPage:
    """List applications submitted to a job owned by the caller's active company."""
    return await service.list_job_applications(
        session,
        storage,
        job_id=job_id,
        user_id=user.id,
        status_filter=status_filter,
        cursor=cursor,
        limit=limit,
    )


@router.get("/applications/mine", response_model=ApplicationsPage)
async def list_my_applications(
    session: Session,
    storage: Files,
    user: CurrentUser,
    status_filter: StatusFilterParam = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_LIMIT,
) -> ApplicationsPage:
    """List applications submitted by the logged-in candidate, newest first."""
    return await service.list_my_applications(
        session,
        storage,
        user.id,
        status_filter=status_filter,
        cursor=cursor,
        limit=limit,
    )


@router.get("/applications/{app_id}", response_model=ApplicationOut)
async def get_application(
    app_id: EntityId,
    session: Session,
    storage: Files,
    user: CurrentUser,
) -> ApplicationOut:
    """Fetch a single application (accessible only to the applicant or job owner)."""
    return await service.get_application(session, storage, app_id=app_id, user_id=user.id)


@router.delete("/applications/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_application(
    app_id: EntityId,
    session: Session,
    redis: RedisClient,
    storage: Files,
    user: CurrentUser,
) -> None:
    """Withdraw the caller's own active application (transitions status to 'withdrawn')."""
    await service.withdraw_application(
        session,
        redis,
        storage,
        app_id=app_id,
        applicant_id=user.id,
    )


@router.patch("/applications/{app_id}/status", response_model=ApplicationOut)
async def update_application_status(
    app_id: EntityId,
    body: StatusUpdateRequest,
    session: Session,
    redis: RedisClient,
    storage: Files,
    user: CurrentUser,
) -> ApplicationOut:
    """Advance an application's status as the job owner; creates a chat on 'contacted'."""
    return await service.update_application_status(
        session,
        redis,
        storage,
        app_id=app_id,
        employer_id=user.id,
        new_status=body.status,
        note=body.note,
    )
