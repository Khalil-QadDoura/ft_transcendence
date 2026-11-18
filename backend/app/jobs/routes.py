"""HTTP endpoints for jobs CRUD (BE-25) and public search (BE-26)."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, OptionalUser
from app.core.storage import Storage, get_storage
from app.db.session import get_session
from app.jobs import repo, service
from app.jobs.schemas import (
    JobCreate,
    JobOut,
    JobSchedule,
    JobSortBy,
    JobsPage,
    JobUpdate,
    JobUrgency,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

Session = Annotated[AsyncSession, Depends(get_session)]
Files = Annotated[Storage, Depends(get_storage)]
JobId = Annotated[int, Path(ge=1, le=repo.MAX_ID)]


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    session: Session,
    storage: Files,
    user: CurrentUser,
) -> JobOut:
    """Create a draft or open job under the caller's active company."""
    return await service.create_job(session, user.id, payload, storage)


@router.get("/mine", response_model=list[JobOut])
async def list_my_jobs(
    session: Session,
    storage: Files,
    user: CurrentUser,
) -> list[JobOut]:
    """List non-deleted jobs owned by the caller's company with view/application counts."""
    return await service.list_my_jobs(session, user.id, storage)


@router.get("/open", response_model=JobsPage)
async def list_open_jobs(
    session: Session,
    storage: Files,
    lat: Annotated[float | None, Query(ge=-90.0, le=90.0, allow_inf_nan=False)] = None,
    lng: Annotated[float | None, Query(ge=-180.0, le=180.0, allow_inf_nan=False)] = None,
    radius_km: Annotated[
        float | None, Query(gt=0.0, le=repo.MAX_RADIUS_KM, allow_inf_nan=False)
    ] = None,
    schedule: Annotated[JobSchedule | None, Query()] = None,
    salary_min: Annotated[Decimal | None, Query(ge=0, allow_inf_nan=False)] = None,
    salary_max: Annotated[Decimal | None, Query(ge=0, allow_inf_nan=False)] = None,
    urgency: Annotated[JobUrgency | None, Query()] = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    position: Annotated[str | None, Query(max_length=100)] = None,
    sort_by: Annotated[JobSortBy, Query()] = "newest",
    cursor: Annotated[int | None, Query(ge=1, le=repo.MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=repo.MAX_SEARCH_LIMIT)] = repo.DEFAULT_SEARCH_LIMIT,
) -> JobsPage:
    """Public search over open jobs: PostGIS radius, full-text, filters, sort, and cursor."""
    return await service.search_open_jobs(
        session,
        storage,
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        schedule=schedule,
        salary_min=salary_min,
        salary_max=salary_max,
        urgency=urgency,
        keyword=keyword,
        position=position,
        sort_by=sort_by,
        cursor=cursor,
        limit=limit,
    )


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: JobId,
    session: Session,
    storage: Files,
    viewer: OptionalUser,
) -> JobOut:
    """Return a job by id; draft jobs are hidden (404) from non-owners."""
    return await service.get_job(session, job_id, viewer.id if viewer else None, storage)


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: JobId,
    payload: JobUpdate,
    session: Session,
    storage: Files,
    user: CurrentUser,
) -> JobOut:
    """Partially update an owned non-deleted job."""
    return await service.update_job(session, job_id, user.id, payload, storage)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: JobId,
    session: Session,
    user: CurrentUser,
) -> None:
    """Soft-delete an owned job."""
    await service.delete_job(session, job_id, user.id)
