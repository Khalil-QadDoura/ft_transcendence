"""Database connection: one engine per app, one session per request."""

from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings


def setup_database(app: FastAPI, settings: Settings) -> None:
    """Give this app its own engine and session factory, built from its own settings.
    The engine keeps a pool of connections. It connects only when a query first runs."""
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.session_factory = async_sessionmaker(app.state.engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a session on this app's database, closed when the request ends."""
    async with request.app.state.session_factory() as session:
        yield session
