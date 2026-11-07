"""Health endpoints: a public one for the proxy and the status page, an internal one for us."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.health import service
from app.health.schemas import DatabaseHealthOut, HealthOut

router = APIRouter(prefix="/health", tags=["health"])  # mounted under /api
internal_router = APIRouter(prefix="/health")  # mounted under /_internal


@router.get("")
async def health() -> HealthOut:
    """The API process is up and answering."""
    return HealthOut(status="ok")


@internal_router.get("/db")
async def database_health(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> DatabaseHealthOut:
    """Can the API reach PostgreSQL? 503 when it cannot."""
    status = await service.database_status(session)
    if status != "ok":
        response.status_code = 503
    return DatabaseHealthOut(database=status)
