"""Business logic and access control for jobs CRUD (BE-25) and search (BE-26)."""

from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies import repo as companies_repo
from app.core.storage import Storage
from app.jobs import repo
from app.jobs.schemas import JobCreate, JobOut, JobSortBy, JobsPage, JobUpdate


def _to_job_out(row: dict[str, Any], storage: Storage | None = None) -> JobOut:
    data = dict(row)
    logo_key = data.pop("company_logo_key", None)
    data.pop("company_owner_user_id", None)
    if storage is not None and "company_logo_url" not in data:
        data["company_logo_url"] = storage.logo_url(logo_key)
    return JobOut.model_validate(data)


async def _require_active_company(session: AsyncSession, user_id: int):
    company = await companies_repo.get_active_by_owner_id(session, user_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active company not found",
        )
    return company


async def create_job(
    session: AsyncSession,
    user_id: int,
    payload: JobCreate,
    storage: Storage | None = None,
) -> JobOut:
    """Create a job under the caller's active company (404 if the user has none)."""
    company = await _require_active_company(session, user_id)
    job = await repo.create_job(
        session,
        owner_id=company.id,
        actor_id=user_id,
        values=payload.model_dump(),
    )
    return _to_job_out(
        repo.job_to_dict(
            job,
            company_name=company.name,
            company_logo_key=company.logo_object_key,
        ),
        storage,
    )


async def list_my_jobs(
    session: AsyncSession, user_id: int, storage: Storage | None = None
) -> list[JobOut]:
    """List non-deleted jobs owned by the caller's active company with counters."""
    company = await _require_active_company(session, user_id)
    rows = await repo.list_company_jobs(session, company.id)
    return [_to_job_out(row, storage) for row in rows]


async def get_job(
    session: AsyncSession,
    job_id: int,
    viewer_id: int | None,
    storage: Storage | None = None,
) -> JobOut:
    """Return a single job; non-open jobs are visible only to the company owner."""
    detail = await repo.get_job_detail(session, job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    owner_user_id = detail.get("company_owner_user_id")
    is_owner = viewer_id is not None and owner_user_id == viewer_id
    if detail["status"] != repo.OPEN and not is_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if not is_owner:
        detail = {**detail, "new_applications_count": 0}
    return _to_job_out(detail, storage)


async def update_job(
    session: AsyncSession,
    job_id: int,
    user_id: int,
    payload: JobUpdate,
    storage: Storage | None = None,
) -> JobOut:
    """Partially update an owned non-deleted job (404 if missing or not owned)."""
    job = await repo.get_owned_job(session, job_id, user_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        updated = await repo.update_job(session, job, actor_id=user_id, values=updates)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    detail = await repo.get_job_detail(session, job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _to_job_out(detail, storage)


async def delete_job(session: AsyncSession, job_id: int, user_id: int) -> None:
    """Soft-delete an owned job (404 if missing, already deleted, or not owned)."""
    job = await repo.get_owned_job(session, job_id, user_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    deleted = await repo.soft_delete_job(session, job, actor_id=user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")


async def search_open_jobs(
    session: AsyncSession,
    storage: Storage | None = None,
    *,
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float | None = None,
    schedule: str | None = None,
    salary_min: Decimal | None = None,
    salary_max: Decimal | None = None,
    urgency: str | None = None,
    keyword: str | None = None,
    position: str | None = None,
    sort_by: JobSortBy = "newest",
    cursor: int | None = None,
    limit: int = repo.DEFAULT_SEARCH_LIMIT,
) -> JobsPage:
    """Public open-job search with PostGIS radius, full-text, filters, sort, and cursor paging."""
    if (lat is None) != (lng is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="query → lat: Both lat and lng must be provided together",
        )
    if radius_km is not None and (lat is None or lng is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="query → radius_km: radius_km requires both lat and lng",
        )
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="query → salary_min: salary_min cannot exceed salary_max",
        )

    clean_keyword = keyword.strip() if keyword else None
    clean_position = position.strip() if position else None

    cursor_distance_m: float | None = None
    if sort_by == "nearest" and lat is not None and lng is not None and cursor is not None:
        cursor_distance_m = await repo.get_job_distance_meters(session, cursor, lat=lat, lng=lng)
        if cursor_distance_m is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="query → cursor: No job has this id: use the next_cursor of the page before",
            )

    rows = await repo.search_open_jobs(
        session,
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        schedule=schedule,
        salary_min=salary_min,
        salary_max=salary_max,
        urgency=urgency,
        keyword=clean_keyword or None,
        position=clean_position or None,
        sort_by=sort_by,
        cursor=cursor,
        cursor_distance_m=cursor_distance_m,
        limit=limit,
    )
    page_rows = rows[:limit]
    items = [_to_job_out(row, storage) for row in page_rows]
    next_cursor = items[-1].id if len(rows) > limit else None
    return JobsPage(items=items, next_cursor=next_cursor)
