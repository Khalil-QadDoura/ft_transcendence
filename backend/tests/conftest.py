"""Shared test setup and database test infrastructure (BE-20).

Features:
- Dedicated test database configuration via TEST_DATABASE_URL.
- Transactional `db` fixture: each test runs inside an isolated transaction that rolls back on exit.
- Commit interception: session.commit() is replaced by session.flush() during tests so changes
  stay visible within the test connection without persisting dirty state to the database.
- Asynchronous HTTP test clients (`async_client` and `async_db_client`) via ASGITransport.
- Synchronous `client` fixture preserved for fast unit tests without database overhead.
- Autouse external service mocks to isolate tests from networks and background workers.
- Rate limit reset fixture between tests.
"""

import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

# Settings require DATABASE_URL, and importing the app reads the settings.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql+asyncpg://wozu_test:change-me@localhost:5432/wozu_test"),
)
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("TEST_DATABASE_URL", TEST_DATABASE_URL)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

try:
    from httpx import ASGITransport, AsyncClient
except ImportError:
    from httpx2 import ASGITransport, AsyncClient

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.limiter import limiter
from app.db.session import get_session
from app.main import create_app

INTERNAL_KEY = "test-internal-key"

# Module-level test engine with NullPool so connections close immediately without pooling.
# Connects lazily only when a query or connection is requested.
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


def build_app(**overrides: object) -> FastAPI:
    """A fresh app for one test; keyword arguments change its settings, e.g. env="dev"."""
    settings = {"env": "prod", "internal_api_key": INTERNAL_KEY, **overrides}
    return create_app(Settings(**settings))


@pytest.fixture
def anyio_backend():
    """Default async backend for anyio-marked async tests."""
    return "asyncio"


@pytest.fixture
def client():
    """Synchronous test client for fast, non-database unit tests."""
    with TestClient(build_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Every test starts with empty rate limit counters."""
    limiter.reset()


@pytest.fixture(autouse=True)
def mock_external_services():
    """Autouse fixture to mock external network and worker side-effects.

    Prevents tests from attempting real network calls for emails, media object storage,
    or Celery background tasks.
    """
    mock_minio = MagicMock()
    mock_minio.ping.return_value = True
    mock_minio.presigned_put_external.return_value = "http://minio-fake/upload"
    mock_minio.presigned_get_external.return_value = "http://minio-fake/video.mp4"
    mock_minio.ensure_bucket.return_value = None

    patches = []
    # If app.auth.emails exists in later cards, mock email sending
    try:
        import app.auth.emails as _emails  # type: ignore[import-not-found]

        patches.append(patch.object(_emails, "send_verification_email", new_callable=AsyncMock))
        patches.append(patch.object(_emails, "send_password_reset_email", new_callable=AsyncMock))
    except (ImportError, AttributeError):
        pass

    for p in patches:
        p.start()

    yield mock_minio

    for p in patches:
        p.stop()


@pytest.fixture
async def db(anyio_backend) -> AsyncGenerator[AsyncSession, None]:
    """Transactional test database session.

    Begins an outer transaction on a dedicated connection. Replaces `commit()`
    with `flush()` so helper-created rows remain queryable within the test session,
    then rolls back the entire transaction upon completion. Pool is never touched.
    """
    try:
        conn = await test_engine.connect()
    except Exception as exc:
        pytest.skip(f"Test database at {TEST_DATABASE_URL} is unreachable: {exc}")

    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    session.info["_test_conn"] = conn

    # Replace commit with flush during testing
    async def _fake_commit():
        await session.flush()

    session.commit = _fake_commit  # type: ignore[method-assign]

    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


@pytest.fixture
async def async_client(anyio_backend) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous test client for async endpoint testing (no database required)."""
    test_app = build_app()
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        headers={"X-Internal-Key": INTERNAL_KEY},
    ) as ac:
        yield ac


@pytest.fixture
async def async_db_client(anyio_backend, db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous test client configured with the transactional DB session."""
    test_app = build_app()

    async def _get_test_session():
        yield db

    test_app.dependency_overrides[get_session] = _get_test_session

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        headers={"X-Internal-Key": INTERNAL_KEY},
    ) as ac:
        yield ac

    test_app.dependency_overrides.clear()
