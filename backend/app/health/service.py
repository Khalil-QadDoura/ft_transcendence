"""The rules: what counts as healthy across all components (BE-31 / M14)."""

import asyncio
from typing import Literal

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import TaskQueue
from app.core.storage import Storage
from app.health import repo
from app.health.schemas import HealthComponentsOut, HealthOut

COMPONENT_TIMEOUT_SEC = 1.0
log = structlog.get_logger(__name__)


async def check_db(session: AsyncSession) -> Literal["ok", "down"]:
    """Probe PostgreSQL connectivity via SELECT 1 within 1.0s."""
    try:
        await asyncio.wait_for(repo.select_one(session), timeout=COMPONENT_TIMEOUT_SEC)
        return "ok"
    except Exception as exc:
        log.warning("health: database check failed", error=repr(exc))
        return "down"


async def check_redis(redis_client: Redis) -> Literal["ok", "down"]:
    """Probe Redis connectivity via ping() within 1.0s."""
    try:
        res = await asyncio.wait_for(redis_client.ping(), timeout=COMPONENT_TIMEOUT_SEC)
        return "ok" if res else "down"
    except Exception as exc:
        log.warning("health: redis check failed", error=repr(exc))
        return "down"


async def check_minio(storage: Storage) -> Literal["ok", "down"]:
    """Probe MinIO connectivity via bucket check within 1.0s."""
    try:
        exists = await asyncio.wait_for(
            asyncio.to_thread(storage.internal.bucket_exists, storage.bucket),
            timeout=COMPONENT_TIMEOUT_SEC,
        )
        return "ok" if exists else "down"
    except Exception as exc:
        log.warning("health: minio check failed", error=repr(exc))
        return "down"


async def check_worker(redis_client: Redis, queue: TaskQueue) -> Literal["ok", "down"]:
    """Probe Celery worker via Redis heartbeat key or Celery inspect ping within 1.0s."""
    # 1. Fast path: Redis heartbeat key set by worker
    try:
        heartbeat = await asyncio.wait_for(
            redis_client.get("worker:heartbeat"),
            timeout=0.3,
        )
        if heartbeat:
            return "ok"
    except Exception:
        pass

    # 2. Celery inspect ping fallback (no worker hostnames or secrets leaked)
    try:

        def _ping() -> bool:
            try:
                inspect = queue.celery.control.inspect(timeout=0.5)
                res = inspect.ping() if inspect else None
                return bool(res)
            except Exception:
                return False

        has_worker = await asyncio.wait_for(
            asyncio.to_thread(_ping),
            timeout=COMPONENT_TIMEOUT_SEC,
        )
        return "ok" if has_worker else "down"
    except Exception as exc:
        log.warning("health: worker check failed", error=repr(exc))
        return "down"


def compute_overall_status(
    db: Literal["ok", "down"],
    redis: Literal["ok", "down"],
    minio: Literal["ok", "down"],
    worker: Literal["ok", "down"],
) -> Literal["ok", "degraded", "down"]:
    """Compute overall service status.

    - "down": when core infrastructure (Postgres or Redis) is unreachable.
    - "degraded": when core is up, but auxiliary services (MinIO or worker) are down.
    - "ok": when all four components are healthy.
    """
    if db != "ok" or redis != "ok":
        return "down"
    if minio == "ok" and worker == "ok":
        return "ok"
    return "degraded"


async def get_health_status(
    session: AsyncSession,
    redis_client: Redis,
    storage: Storage,
    queue: TaskQueue,
) -> HealthOut:
    """Run all 4 component probes concurrently in <= 1.0s."""
    db_res, redis_res, minio_res, worker_res = await asyncio.gather(
        check_db(session),
        check_redis(redis_client),
        check_minio(storage),
        check_worker(redis_client, queue),
    )
    overall = compute_overall_status(db_res, redis_res, minio_res, worker_res)
    return HealthOut(
        status=overall,
        components=HealthComponentsOut(
            db=db_res,
            redis=redis_res,
            minio=minio_res,
            worker=worker_res,
        ),
    )


async def database_status(session: AsyncSession) -> str:
    """Return "ok" if PostgreSQL answers in time, otherwise "unreachable"."""
    status = await check_db(session)
    return "ok" if status == "ok" else "unreachable"
