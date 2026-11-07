"""Database connection: one engine per process, one session per request."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# The engine keeps a pool of connections. It connects only when a query first runs.
engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a session for this request, closed when the request ends."""
    async with SessionLocal() as session:
        yield session
