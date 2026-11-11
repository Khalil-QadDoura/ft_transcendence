"""Shared test setup.

Most tests need no database: the engine connects only when a query first runs. The database
tests (test_schema.py, test_auth.py, test_users.py) need a real PostgreSQL with PostGIS and
are skipped without one, so `pytest -q` works everywhere.
"""

import asyncio
import os
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# Settings require DATABASE_URL and JWT_SECRET, and importing the app reads the settings.
# Made-up values, for tests only.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-0123456789abcdef")

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.limiter import limiter
from app.core.mailer import get_mailer
from app.db.session import get_session
from app.main import create_app

INTERNAL_KEY = "test-internal-key"
BACKEND_DIR = Path(__file__).resolve().parents[1]

# The database tests delete what they find (every table, or every user), so they never use
# DATABASE_URL: only TEST_DATABASE_URL, and only if its database name contains "test".
# To run them:
#     docker run -d --name wozu-test-db -p 5432:5432 -e POSTGRES_PASSWORD=test \
#         -e POSTGRES_DB=wozu_test postgis/postgis:15-3.4
#     TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:5432/wozu_test pytest -q
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def database_skip_reason() -> str | None:
    """Why the database tests cannot run here, or None when they can."""
    if not TEST_DATABASE_URL:
        return "TEST_DATABASE_URL is not set"
    url = make_url(TEST_DATABASE_URL)
    if "test" not in (url.database or ""):
        return "the TEST_DATABASE_URL database name must contain 'test'"
    try:
        socket.create_connection((url.host or "localhost", url.port or 5432), timeout=2).close()
    except OSError:
        return f"no database answers at {url.host}:{url.port}"
    return None


# Checked once per test run. A database test file starts with `pytestmark = needs_database`.
DATABASE_SKIP_REASON = database_skip_reason()
needs_database = pytest.mark.skipif(
    DATABASE_SKIP_REASON is not None, reason=str(DATABASE_SKIP_REASON)
)


def alembic(*args: str) -> str:
    """Run an Alembic command on the test database, as the container does on start."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr


def sql(statement: str, **params) -> list:
    """Run one SQL statement on the test database; returns its rows."""

    async def run() -> list:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as connection:
            result = await connection.execute(text(statement), params)
            rows = result.all() if result.returns_rows else []
        await engine.dispose()
        return rows

    return asyncio.run(run())


def build_app(**overrides: object) -> FastAPI:
    """A fresh app for one test; keyword arguments change its settings, e.g. env="dev".

    The email links always start with https://localhost here, whatever FRONTEND_BASE_URL the
    environment has (`make test` passes the one from .env, e.g. https://localhost:18443).
    """
    settings = {
        "env": "prod",
        "internal_api_key": INTERNAL_KEY,
        "frontend_base_url": "https://localhost",
        **overrides,
    }
    app = create_app(Settings(**settings))
    # Real SMTP/Brevo tests instantiate Mailer directly. Route tests never send mail.
    mailbox = TestMailbox()
    app.state.test_mailbox = mailbox
    app.dependency_overrides[get_mailer] = lambda: mailbox
    return app


@pytest.fixture
def client():
    with TestClient(build_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Every test starts with empty rate limit counters."""
    limiter.reset()


class TestMailbox:
    """Record outgoing route emails without contacting SMTP or Brevo."""

    __test__ = False

    def __init__(self):
        self.sent = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def transactional_session() -> AsyncIterator[AsyncSession]:
    """Isolate real commits/rollbacks with savepoints inside an outer transaction.

    Only the explicit test database is allowed, using the same guard as main's
    schema/auth tests. No DATABASE_URL fallback, no secret-bearing exception skip.
    """
    if DATABASE_SKIP_REASON is not None:
        pytest.skip(DATABASE_SKIP_REASON)
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    yield session
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def db(anyio_backend) -> AsyncIterator[AsyncSession]:
    """One isolated transaction per test; migrations remain explicit in each suite."""
    async with transactional_session() as session:
        yield session


@pytest.fixture
async def async_client(anyio_backend) -> AsyncIterator[httpx2.AsyncClient]:
    """ASGI client for async tests that do not need a database session."""
    app = build_app()
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Internal-Key": INTERNAL_KEY},
    ) as test_client:
        yield test_client


@pytest.fixture
async def async_db_client(anyio_backend, db) -> AsyncIterator[httpx2.AsyncClient]:
    """App routes use the same isolated session as the test's db fixture."""
    app = build_app(database_url=TEST_DATABASE_URL)

    async def override_session():
        yield db

    app.dependency_overrides[get_session] = override_session
    try:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Internal-Key": INTERNAL_KEY},
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
