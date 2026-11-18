"""Business logic for applications: apply guard, state machine, live events, and job views."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications import repo
from app.applications.constants import (
    APPLICANT_TRANSITIONS,
    EMPLOYER_TRANSITIONS,
    EVENT_APPLICATION_CREATED,
    EVENT_APPLICATION_UPDATED,
    JOB_VIEW_DEDUP_TTL_SEC,
)
from app.applications.models import Application
from app.applications.schemas import ApplicationOut, ApplicationsPage
from app.companies.repo import ACTIVE as COMPANY_ACTIVE
from app.conversations import repo as conversations_repo
from app.core.storage import Storage
from app.jobs.repo import OPEN as JOB_OPEN
from app.media.constants import VIEW_URL_EXPIRES_SEC
from app.realtime import service as realtime_service
from app.users.models import User

log = structlog.get_logger(__name__)


def _serialize_application(detail: dict[str, Any], storage: Storage) -> ApplicationOut:
    app: Application = detail["application"]
    video_key = detail.get("video_object_key")
    video_lifecycle = detail.get("video_lifecycle_status")
    video_url = (
        storage.download_url(video_key, timedelta(seconds=VIEW_URL_EXPIRES_SEC))
        if video_key and video_lifecycle != "deleted"
        else None
    )
    return ApplicationOut(
        id=app.id,
        job_id=app.job_id,
        applicant_id=app.applicant_id,
        company_id=app.company_id,
        intro_video_id=app.intro_video_id,
        status=app.status,
        cover_note=app.cover_note,
        conversation_id=app.conversation_id,
        applied_at=app.applied_at,
        updated_at=app.updated_at,
        viewed_at=app.viewed_at,
        job_title=detail.get("job_title"),
        company_name=detail.get("company_name"),
        applicant_first_name=detail.get("applicant_first_name"),
        applicant_last_name=detail.get("applicant_last_name"),
        applicant_position=detail.get("applicant_position"),
        applicant_avatar_url=storage.avatar_url(detail.get("applicant_avatar_key")),
        intro_video_url=video_url,
    )


def _profile_is_complete(user: User) -> bool:
    return bool(
        (user.first_name or "").strip()
        and (user.last_name or "").strip()
        and (user.position or "").strip()
    )


async def apply(
    session: AsyncSession,
    redis: Redis,
    storage: Storage,
    *,
    job_id: int,
    applicant: User,
    cover_note: str | None,
) -> ApplicationOut:
    """Validate guards, submit an application to an open job, and notify the employer."""
    job_and_company = await repo.get_job_and_company(session, job_id)
    if job_and_company is None or job_and_company[0].status != JOB_OPEN:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found or not accepting applications",
        )
    job, company = job_and_company

    if company.owner_user_id == applicant.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot apply to your own company's job",
        )

    existing = await repo.get_application_by_job_and_user(session, job.id, applicant.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already applied to this job",
        )

    if not _profile_is_complete(applicant):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "profile_incomplete", "next_step": "profile"},
        )

    video_id = await repo.get_posted_approved_video_id(session, applicant.id)
    if video_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "no_video", "next_step": "video"},
        )

    try:
        application = await repo.create_application(
            session,
            job_id=job.id,
            applicant_id=applicant.id,
            company_id=company.id,
            intro_video_id=video_id,
            cover_note=cover_note,
        )
        await repo.log_event(
            session,
            application_id=application.id,
            actor_id=applicant.id,
            from_status=None,
            to_status="submitted",
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already applied to this job",
        ) from exc

    detail = await repo.get_application_detail(session, application.id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    out = _serialize_application(detail, storage)
    await realtime_service.send_to_user(
        redis, company.owner_user_id, EVENT_APPLICATION_CREATED, out
    )
    return out


async def list_my_applications(
    session: AsyncSession,
    storage: Storage,
    applicant_id: int,
    *,
    status_filter: str | None,
    cursor: int | None,
    limit: int,
) -> ApplicationsPage:
    """List cursor-paginated applications belonging to the logged-in candidate."""
    rows = await repo.list_mine(
        session,
        applicant_id,
        status=status_filter,
        cursor=cursor,
        limit=limit,
    )
    items = rows[:limit]
    return ApplicationsPage(
        items=[_serialize_application(row, storage) for row in items],
        next_cursor=items[-1]["application"].id if len(rows) > limit else None,
    )


async def list_job_applications(
    session: AsyncSession,
    storage: Storage,
    *,
    job_id: int,
    user_id: int,
    status_filter: str | None,
    cursor: int | None,
    limit: int,
) -> ApplicationsPage:
    """List cursor-paginated applications for one job owned by the caller's company."""
    job_and_company = await repo.get_job_and_company(session, job_id)
    if job_and_company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    _, company = job_and_company
    if company.owner_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the job owner")

    rows = await repo.list_for_job(
        session,
        job_id,
        status=status_filter,
        cursor=cursor,
        limit=limit,
    )
    items = rows[:limit]
    return ApplicationsPage(
        items=[_serialize_application(row, storage) for row in items],
        next_cursor=items[-1]["application"].id if len(rows) > limit else None,
    )


async def get_application(
    session: AsyncSession,
    storage: Storage,
    *,
    app_id: int,
    user_id: int,
) -> ApplicationOut:
    """Fetch a single application if the caller is the applicant or the active job owner."""
    detail = await repo.get_application_detail(session, app_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    app: Application = detail["application"]
    is_applicant = app.applicant_id == user_id
    is_owner = (
        detail["company_status"] == COMPANY_ACTIVE and detail["company_owner_user_id"] == user_id
    )
    if not is_applicant and not is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return _serialize_application(detail, storage)


async def withdraw_application(
    session: AsyncSession,
    redis: Redis,
    storage: Storage,
    *,
    app_id: int,
    applicant_id: int,
) -> None:
    """Withdraw the caller's own active application and notify the employer."""
    detail = await repo.get_application_detail(session, app_id)
    if detail is None or detail["application"].applicant_id != applicant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    await _transition_status(
        session,
        redis,
        storage,
        detail=detail,
        actor_id=applicant_id,
        new_status="withdrawn",
        note=None,
        actor_is_employer=False,
    )


async def update_application_status(
    session: AsyncSession,
    redis: Redis,
    storage: Storage,
    *,
    app_id: int,
    employer_id: int,
    new_status: str,
    note: str | None,
) -> ApplicationOut:
    """Advance an application's status as the active company owner and notify the applicant."""
    detail = await repo.get_application_detail(session, app_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    if detail["company_status"] != COMPANY_ACTIVE or detail["company_owner_user_id"] != employer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the job owner")

    return await _transition_status(
        session,
        redis,
        storage,
        detail=detail,
        actor_id=employer_id,
        new_status=new_status,
        note=note,
        actor_is_employer=True,
    )


async def _ensure_contact_conversation_in_tx(
    session: AsyncSession, *, app: Application, employer_user_id: int
) -> int:
    """Get or create a direct conversation inside the current transaction and link app_id."""
    existing = await conversations_repo.find_direct_conversation(
        session, employer_user_id, app.applicant_id
    )
    if existing is None:
        await conversations_repo.lock_direct_pair(session, employer_user_id, app.applicant_id)
        existing = await conversations_repo._query_direct_conversation(
            session, employer_user_id, app.applicant_id
        )
    if existing is None:
        conv = await conversations_repo.create_conversation(
            session, type="direct", job_id=app.job_id
        )
        await conversations_repo.add_participant(session, conv.id, employer_user_id)
        await conversations_repo.add_participant(session, conv.id, app.applicant_id)
    else:
        conv = existing

    await repo.link_conversation_application(session, conv.id, app_id=app.id, job_id=app.job_id)
    return conv.id


async def _transition_status(
    session: AsyncSession,
    redis: Redis,
    storage: Storage,
    *,
    detail: dict[str, Any],
    actor_id: int,
    new_status: str,
    note: str | None,
    actor_is_employer: bool,
) -> ApplicationOut:
    app: Application = detail["application"]
    old_status = app.status
    transitions = EMPLOYER_TRANSITIONS if actor_is_employer else APPLICANT_TRANSITIONS
    allowed = transitions.get(old_status, ())
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transition '{old_status}' -> '{new_status}' is not allowed",
        )

    viewed_at: datetime | None = None
    if new_status == "viewed" and app.viewed_at is None:
        viewed_at = datetime.now(UTC)

    conversation_id: int | None = None
    if new_status == "contacted":
        conversation_id = await _ensure_contact_conversation_in_tx(
            session, app=app, employer_user_id=actor_id
        )

    updated = await repo.update_status_if_matches(
        session,
        app.id,
        expected_status=old_status,
        new_status=new_status,
        conversation_id=conversation_id,
        viewed_at=viewed_at,
    )
    if updated is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application status changed concurrently; please retry",
        )

    await repo.log_event(
        session,
        application_id=app.id,
        actor_id=actor_id,
        from_status=old_status,
        to_status=new_status,
        note=note,
    )
    await session.commit()

    updated_detail = await repo.get_application_detail(session, app.id)
    if updated_detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    out = _serialize_application(updated_detail, storage)
    if actor_is_employer:
        await realtime_service.send_to_user(redis, app.applicant_id, EVENT_APPLICATION_UPDATED, out)
    elif detail["company_status"] == COMPANY_ACTIVE:
        await realtime_service.send_to_user(
            redis, detail["company_owner_user_id"], EVENT_APPLICATION_UPDATED, out
        )
    return out


async def record_job_view(
    session: AsyncSession,
    redis: Redis,
    *,
    job_id: int,
    viewer_id: int | None,
    client_ip: str | None = None,
) -> None:
    """Count at most one job view per viewer per job every 24 hours (Redis NX + TTL)."""
    job_and_company = await repo.get_job_and_company(session, job_id)
    if job_and_company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    job, _ = job_and_company
    if job.status != JOB_OPEN:
        return

    viewer_key = f"u:{viewer_id}" if viewer_id is not None else f"ip:{client_ip or 'anon'}"
    redis_key = f"job:view:{job_id}:{viewer_key}"
    try:
        is_first_view = await redis.set(redis_key, "1", ex=JOB_VIEW_DEDUP_TTL_SEC, nx=True)
    except RedisError:
        log.warning("job view dedup skipped: redis unavailable", job_id=job_id, exc_info=True)
        return

    if is_first_view:
        await repo.record_view(session, job_id, viewer_id)
        await session.commit()
