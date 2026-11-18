"""Celery tasks for intro-video moderation, stuck-video recovery, and worker heartbeat (BE-29)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import redis
import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.queue import MODERATION_TASK
from app.media.constants import WORKER_HEARTBEAT_KEY
from app.media.models import IntroVideo
from app.media.moderation import run_moderation
from app.worker.celery_app import celery_app

log = structlog.get_logger(__name__)


def write_worker_heartbeat(redis_url: str, ttl_sec: int) -> None:
    """Refresh worker:heartbeat in Redis so GET /api/health and Docker healthcheck see us up."""
    try:
        with redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2) as client:
            client.set(WORKER_HEARTBEAT_KEY, "1", ex=ttl_sec)
    except Exception:
        log.warning("worker heartbeat write failed", exc_info=True)


@celery_app.task(name=MODERATION_TASK)
def run_moderation_task(video_id: int, object_key: str) -> str:
    """Download, inspect, and moderate one uploaded intro video."""
    return asyncio.run(run_moderation(video_id, object_key))


@celery_app.task(name="app.worker.tasks.moderation.heartbeat")
def heartbeat() -> None:
    """Periodic beat task keeping worker:heartbeat alive in Redis."""
    settings = get_settings()
    write_worker_heartbeat(settings.redis_url, settings.worker_heartbeat_ttl_sec)


async def requeue_stuck_videos(
    session: AsyncSession,
    *,
    enqueue_fn: Callable[[int, str], object],
    stuck_minutes: int,
) -> list[int]:
    """Find non-deleted pending videos idle longer than stuck_minutes and re-enqueue them."""
    cutoff = datetime.now(UTC) - timedelta(minutes=stuck_minutes)
    rows = (
        await session.execute(
            select(IntroVideo.id, IntroVideo.object_key)
            .where(
                IntroVideo.moderation_status == "pending",
                IntroVideo.lifecycle_status != "deleted",
                IntroVideo.updated_at < cutoff,
            )
            .order_by(IntroVideo.id)
        )
    ).all()
    if not rows:
        return []

    video_ids = [int(row.id) for row in rows]
    # Bump updated_at before re-enqueueing so back-to-back beat ticks do not duplicate work.
    await session.execute(
        update(IntroVideo).where(IntroVideo.id.in_(video_ids)).values(updated_at=func.now())
    )
    await session.commit()

    for row in rows:
        log.info("requeueing stuck pending video", video_id=row.id)
        enqueue_fn(int(row.id), str(row.object_key))
    return video_ids


async def _requeue_stuck_async(settings: Settings | None = None) -> list[int]:
    cfg = settings or get_settings()
    engine = create_async_engine(cfg.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await requeue_stuck_videos(
                session,
                enqueue_fn=lambda vid, key: run_moderation_task.delay(vid, key),
                stuck_minutes=cfg.moderation_stuck_minutes,
            )
    finally:
        await engine.dispose()


@celery_app.task(name="app.worker.tasks.moderation.requeue_stuck")
def requeue_stuck() -> list[int]:
    """Periodic beat task that re-enqueues intro videos stuck in pending."""
    return asyncio.run(_requeue_stuck_async())
