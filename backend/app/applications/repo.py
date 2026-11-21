"""Database queries for applications, application events, and job views (BE-28)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application, ApplicationEvent, JobView
from app.companies.models import Company
from app.companies.repo import ACTIVE as COMPANY_ACTIVE
from app.conversations.models import Conversation
from app.jobs.models import Job
from app.jobs.repo import DELETED as JOB_DELETED
from app.media.models import IntroVideo
from app.users.models import User


def _application_detail_stmt():
    return (
        select(
            Application,
            Job.title.label("job_title"),
            Company.name.label("company_name"),
            Company.owner_user_id.label("company_owner_user_id"),
            Company.status.label("company_status"),
            User.first_name.label("applicant_first_name"),
            User.last_name.label("applicant_last_name"),
            User.position.label("applicant_position"),
            User.avatar_object_key.label("applicant_avatar_key"),
            IntroVideo.object_key.label("video_object_key"),
            IntroVideo.lifecycle_status.label("video_lifecycle_status"),
        )
        .join(Job, Job.id == Application.job_id)
        .join(Company, Company.id == Application.company_id)
        .join(User, User.id == Application.applicant_id)
        .outerjoin(IntroVideo, IntroVideo.id == Application.intro_video_id)
    )


def _row_to_detail(row: Any) -> dict[str, Any]:
    return {
        "application": row.Application,
        "job_title": row.job_title,
        "company_name": row.company_name,
        "company_owner_user_id": row.company_owner_user_id,
        "company_status": row.company_status,
        "applicant_first_name": row.applicant_first_name,
        "applicant_last_name": row.applicant_last_name,
        "applicant_position": row.applicant_position,
        "applicant_avatar_key": row.applicant_avatar_key,
        "video_object_key": row.video_object_key,
        "video_lifecycle_status": row.video_lifecycle_status,
    }


async def get_application_detail(session: AsyncSession, app_id: int) -> dict[str, Any] | None:
    """Fetch one application with joined job, company, applicant, and intro video metadata."""
    stmt = _application_detail_stmt().where(Application.id == app_id).limit(1)
    row = (await session.execute(stmt)).one_or_none()
    return _row_to_detail(row) if row is not None else None


async def get_application_by_job_and_user(
    session: AsyncSession, job_id: int, applicant_id: int
) -> Application | None:
    """Return an existing application for the (job_id, applicant_id) pair, if any."""
    stmt = (
        select(Application)
        .where(Application.job_id == job_id, Application.applicant_id == applicant_id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_job_and_company(session: AsyncSession, job_id: int) -> tuple[Job, Company] | None:
    """Return a non-deleted job with its active owning company, or None."""
    stmt = (
        select(Job, Company)
        .join(Company, Company.id == Job.owner_id)
        .where(
            Job.id == job_id,
            Job.status != JOB_DELETED,
            Company.status == COMPANY_ACTIVE,
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).one_or_none()
    return (row.Job, row.Company) if row is not None else None


async def get_posted_approved_video_id(session: AsyncSession, user_id: int) -> int | None:
    """Return the user's posted and moderation-approved intro video id, or None."""
    stmt = (
        select(IntroVideo.id)
        .where(
            IntroVideo.user_id == user_id,
            IntroVideo.moderation_status == "approved",
            IntroVideo.lifecycle_status == "posted",
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_application(
    session: AsyncSession,
    *,
    job_id: int,
    applicant_id: int,
    company_id: int,
    intro_video_id: int | None,
    cover_note: str | None,
) -> Application:
    """Insert a new submitted application row and flush to obtain its id."""
    application = Application(
        job_id=job_id,
        applicant_id=applicant_id,
        company_id=company_id,
        intro_video_id=intro_video_id,
        cover_note=cover_note,
    )
    session.add(application)
    await session.flush()
    return application


async def log_event(
    session: AsyncSession,
    *,
    application_id: int,
    actor_id: int | None,
    from_status: str | None,
    to_status: str,
    note: str | None = None,
) -> ApplicationEvent:
    """Append one audit row to application_events."""
    event = ApplicationEvent(
        application_id=application_id,
        actor_id=actor_id,
        from_status=from_status,
        to_status=to_status,
        note=note,
    )
    session.add(event)
    await session.flush()
    return event


async def update_status_if_matches(
    session: AsyncSession,
    app_id: int,
    *,
    expected_status: str,
    new_status: str,
    conversation_id: int | None = None,
    viewed_at: datetime | None = None,
) -> Application | None:
    """Atomically transition status only if the current row still holds expected_status."""
    values: dict[str, Any] = {"status": new_status, "updated_at": func.now()}
    if conversation_id is not None:
        values["conversation_id"] = conversation_id
    if viewed_at is not None:
        values["viewed_at"] = viewed_at
    stmt = (
        update(Application)
        .where(Application.id == app_id, Application.status == expected_status)
        .values(**values)
        .returning(Application)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def link_conversation_application(
    session: AsyncSession, conv_id: int, *, app_id: int, job_id: int
) -> None:
    """Attach the application (and job if absent) onto the direct conversation."""
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conv_id)
        .values(
            application_id=app_id,
            job_id=func.coalesce(Conversation.job_id, job_id),
        )
    )


async def list_mine(
    session: AsyncSession,
    applicant_id: int,
    *,
    status: str | None,
    cursor: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Return limit + 1 applications submitted by applicant_id, newest first."""
    stmt = _application_detail_stmt().where(Application.applicant_id == applicant_id)
    if status is not None:
        stmt = stmt.where(Application.status == status)
    if cursor is not None:
        stmt = stmt.where(Application.id < cursor)
    stmt = stmt.order_by(Application.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    return [_row_to_detail(r) for r in rows]


async def list_for_job(
    session: AsyncSession,
    job_id: int,
    *,
    status: str | None,
    cursor: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Return limit + 1 applications submitted to job_id, newest first."""
    stmt = _application_detail_stmt().where(Application.job_id == job_id)
    if status is not None:
        stmt = stmt.where(Application.status == status)
    if cursor is not None:
        stmt = stmt.where(Application.id < cursor)
    stmt = stmt.order_by(Application.id.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    return [_row_to_detail(r) for r in rows]


async def record_view(session: AsyncSession, job_id: int, viewer_id: int | None) -> JobView:
    """Insert a counted job view row."""
    view = JobView(job_id=job_id, viewer_id=viewer_id)
    session.add(view)
    await session.flush()
    return view
