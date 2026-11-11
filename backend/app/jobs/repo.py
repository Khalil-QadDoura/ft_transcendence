"""Database queries for the jobs domain (BE-25)."""

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application, JobView
from app.companies.models import Company
from app.companies.repo import ACTIVE as COMPANY_ACTIVE
from app.jobs.models import Job

DRAFT = "draft"
OPEN = "open"
DELETED = "deleted"


def _counters_subqueries():
    views_sub = (
        select(
            JobView.job_id.label("job_id"),
            func.count(JobView.id).label("views_count"),
        )
        .group_by(JobView.job_id)
        .subquery()
    )
    apps_sub = (
        select(
            Application.job_id.label("job_id"),
            func.count(case((Application.status != "withdrawn", 1))).label("applications_count"),
            func.count(case((Application.status == "submitted", 1))).label(
                "new_applications_count"
            ),
        )
        .group_by(Application.job_id)
        .subquery()
    )
    return views_sub, apps_sub


def _build_jobs_query():
    views_sub, apps_sub = _counters_subqueries()
    stmt = (
        select(
            Job,
            Company.name.label("company_name"),
            Company.owner_user_id.label("company_owner_user_id"),
            func.coalesce(views_sub.c.views_count, 0).label("views_count"),
            func.coalesce(apps_sub.c.applications_count, 0).label("applications_count"),
            func.coalesce(apps_sub.c.new_applications_count, 0).label("new_applications_count"),
        )
        .join(Company, Company.id == Job.owner_id)
        .outerjoin(views_sub, views_sub.c.job_id == Job.id)
        .outerjoin(apps_sub, apps_sub.c.job_id == Job.id)
        .where(Job.status != DELETED, Company.status == COMPANY_ACTIVE)
    )
    return stmt


def job_to_dict(
    job: Job,
    *,
    company_name: str | None,
    views_count: int = 0,
    applications_count: int = 0,
    new_applications_count: int = 0,
    company_owner_user_id: int | None = None,
) -> dict[str, Any]:
    """Flatten a Job ORM row with company and counter columns into schema kwargs."""
    data: dict[str, Any] = {
        "id": job.id,
        "owner_id": job.owner_id,
        "company_name": company_name,
        "title": job.title,
        "description": job.description,
        "status": job.status,
        "latitude": job.latitude,
        "longitude": job.longitude,
        "location": job.location,
        "salary_amount": job.salary_amount,
        "salary_type": job.salary_type,
        "salary_currency": job.salary_currency,
        "schedule": job.schedule,
        "urgency": job.urgency,
        "views_count": int(views_count or 0),
        "applications_count": int(applications_count or 0),
        "new_applications_count": int(new_applications_count or 0),
        "created_by_id": job.created_by_id,
        "updated_by_id": job.updated_by_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }
    if company_owner_user_id is not None:
        data["company_owner_user_id"] = company_owner_user_id
    return data


async def get_job_detail(session: AsyncSession, job_id: int) -> dict[str, Any] | None:
    """Return a non-deleted job with its active company and counters, or None."""
    stmt = _build_jobs_query().where(Job.id == job_id).limit(1)
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None
    return job_to_dict(
        row.Job,
        company_name=row.company_name,
        company_owner_user_id=row.company_owner_user_id,
        views_count=row.views_count,
        applications_count=row.applications_count,
        new_applications_count=row.new_applications_count,
    )


async def list_company_jobs(session: AsyncSession, company_id: int) -> list[dict[str, Any]]:
    """Return all non-deleted jobs for one company with view and application counters."""
    stmt = (
        _build_jobs_query()
        .where(Job.owner_id == company_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        job_to_dict(
            row.Job,
            company_name=row.company_name,
            views_count=row.views_count,
            applications_count=row.applications_count,
            new_applications_count=row.new_applications_count,
        )
        for row in rows
    ]


async def get_owned_job(session: AsyncSession, job_id: int, owner_user_id: int) -> Job | None:
    """Return a non-deleted job only if owned by the caller's active company."""
    stmt = (
        select(Job)
        .join(Company, Company.id == Job.owner_id)
        .where(
            Job.id == job_id,
            Job.status != DELETED,
            Company.status == COMPANY_ACTIVE,
            Company.owner_user_id == owner_user_id,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_job(
    session: AsyncSession,
    *,
    owner_id: int,
    actor_id: int,
    values: dict[str, Any],
) -> Job:
    """Insert a new job row; PostgreSQL computes location_point and search_vector."""
    job = Job(
        owner_id=owner_id,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        **values,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def update_job(
    session: AsyncSession,
    job: Job,
    *,
    actor_id: int,
    values: dict[str, Any],
) -> Job:
    """Persist field changes onto an owned job row."""
    for key, value in values.items():
        if hasattr(job, key):
            setattr(job, key, value)
    job.updated_by_id = actor_id
    await session.commit()
    await session.refresh(job)
    return job


async def soft_delete_job(session: AsyncSession, job: Job, *, actor_id: int) -> None:
    """Soft-delete a job by setting status to 'deleted'."""
    job.status = DELETED
    job.updated_by_id = actor_id
    await session.commit()
