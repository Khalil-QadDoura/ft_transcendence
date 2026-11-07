"""The rules: what counts as healthy."""

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.health import repo

DB_CHECK_TIMEOUT_SEC = 3
log = structlog.get_logger(__name__)


async def database_status(session: AsyncSession) -> str:
    """Return "ok" if PostgreSQL answers in time, otherwise "unreachable"."""
    try:
        await asyncio.wait_for(repo.select_one(session), timeout=DB_CHECK_TIMEOUT_SEC)
    except Exception as exc:  # down, wrong password, timeout: all mean unreachable
        log.warning("database check failed", error=repr(exc))
        return "unreachable"
    return "ok"
