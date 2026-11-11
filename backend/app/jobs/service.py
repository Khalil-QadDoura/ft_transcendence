"""Business logic and access control for jobs CRUD (BE-25)."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies import repo as companies_repo
from app.jobs import repo
from app.jobs.schemas import JobCreate, JobOut, JobUpdate


async def _require_active_company(session: AsyncSession, user_id: int):
    company = await companies_repo.get_active_by_owner_id(session, user_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active company not found",
        )
    return company


async def create_job(session: AsyncSession, user_id: int, payload: JobCreate) -> JobOut:
    """Create a job under the caller's active company (404 if the user has none)."""
    company = await _require_active_company(session, user_id)
    job = await repo.create_job(
        session,
        owner_id=company.id,
        actor_id=user_id,
        values=payload.model_dump(),
    )
    return JobOut.model_validate(repo.job_to_dict(job, company_name=company.name))


async def list_my_jobs(session: AsyncSession, user_id: int) -> list[JobOut]:
    """List non-deleted jobs owned by the caller's active company with counters."""
    company = await _require_active_company(session, user_id)
    rows = await repo.list_company_jobs(session, company.id)
    return [JobOut.model_validate(row) for row in rows]


async def get_job(session: AsyncSession, job_id: int, viewer_id: int | None) -> JobOut:
    """Return a single job; non-open jobs are visible only to the company owner."""
    detail = await repo.get_job_detail(session, job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    owner_user_id = detail.pop("company_owner_user_id", None)
    is_owner = viewer_id is not None and owner_user_id == viewer_id
    if detail["status"] != repo.OPEN and not is_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if not is_owner:
        detail["new_applications_count"] = 0
    return JobOut.model_validate(detail)


async def update_job(
    session: AsyncSession, job_id: int, user_id: int, payload: JobUpdate
) -> JobOut:
    """Partially update an owned non-deleted job (404 if missing or not owned)."""
    job = await repo.get_owned_job(session, job_id, user_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        await repo.update_job(session, job, actor_id=user_id, values=updates)
    detail = await repo.get_job_detail(session, job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    detail.pop("company_owner_user_id", None)
    return JobOut.model_validate(detail)


async def delete_job(session: AsyncSession, job_id: int, user_id: int) -> None:
    """Soft-delete an owned job (404 if missing, already deleted, or not owned)."""
    job = await repo.get_owned_job(session, job_id, user_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    await repo.soft_delete_job(session, job, actor_id=user_id)
