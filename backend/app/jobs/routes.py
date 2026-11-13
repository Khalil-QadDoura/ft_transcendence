"""HTTP endpoints for jobs CRUD and owner listings (BE-25)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, OptionalUser
from app.db.session import get_session
from app.jobs import service
from app.jobs.schemas import JobCreate, JobOut, JobUpdate

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> JobOut:
    """Create a draft or open job under the caller's active company."""
    return await service.create_job(session, user.id, payload)


@router.get("/mine", response_model=list[JobOut])
async def list_my_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> list[JobOut]:
    """List non-deleted jobs owned by the caller's company with view/application counts."""
    return await service.list_my_jobs(session, user.id)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    viewer: OptionalUser,
) -> JobOut:
    """Return a job by id; draft jobs are hidden (404) from non-owners."""
    return await service.get_job(session, job_id, viewer.id if viewer else None)


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: int,
    payload: JobUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> JobOut:
    """Partially update an owned non-deleted job."""
    return await service.update_job(session, job_id, user.id, payload)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> None:
    """Soft-delete an owned job."""
    await service.delete_job(session, job_id, user.id)
