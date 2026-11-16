"""Health endpoints: a public one for the proxy and status page, an internal one for us."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import TaskQueue, get_queue
from app.core.redis_client import get_redis
from app.core.storage import Storage, get_storage
from app.db.session import get_session
from app.health import service
from app.health.schemas import DatabaseHealthOut, HealthOut

router = APIRouter(prefix="/health", tags=["health"])  # mounted under /api
internal_router = APIRouter(prefix="/health")  # mounted under /_internal


@router.get("", response_model=HealthOut)
async def health(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    storage: Annotated[Storage, Depends(get_storage)],
    queue: Annotated[TaskQueue, Depends(get_queue)],
) -> HealthOut:
    """The API process is up and answering with per-component status (BE-31 / M14).

    Returns 200 when core is ok ('ok' or 'degraded'); returns 503 when core is 'down'.
    """
    health_data = await service.get_health_status(session, redis, storage, queue)
    if health_data.status == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health_data


@internal_router.get("/db", response_model=DatabaseHealthOut)
async def database_health(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> DatabaseHealthOut:
    """Can the API reach PostgreSQL? 503 when it cannot."""
    db_stat = await service.database_status(session)
    if db_stat != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DatabaseHealthOut(database=db_stat)
