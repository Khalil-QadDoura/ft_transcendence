"""Shared test setup.

Most tests need no database: the engine connects only when a query first runs. The database
tests (test_schema.py, test_auth.py, test_users.py) need a real PostgreSQL with PostGIS and
are skipped without one, so `pytest -q` works everywhere. The WebSocket tests (test_realtime.py)
need a real Redis as well.
"""

import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from email import message_from_bytes, policy
from pathlib import Path

# Settings require DATABASE_URL and JWT_SECRET, and importing the app reads the settings.
# Made-up values, for tests only.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-0123456789abcdef")

import httpx2
import pytest
import redis
import uvicorn
from aiosmtpd.controller import Controller
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.limiter import limiter
from app.core.mailer import get_mailer
from app.core.queue import get_queue
from app.core.redis_client import get_redis
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


# The WebSocket tests (test_realtime.py) also need a real Redis. They use TEST_REDIS_URL only,
# never REDIS_URL, and delete only the keys they make (names starting with "ws:"). To run them:
#     docker run -d --name wozu-test-redis -p 6379:6379 redis:7-alpine
#     TEST_REDIS_URL=redis://localhost:6379/1 pytest -q   (with TEST_DATABASE_URL as above)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "")


def redis_skip_reason() -> str | None:
    """Why the Redis tests cannot run here, or None when they can."""
    if not TEST_REDIS_URL:
        return "TEST_REDIS_URL is not set"
    try:
        with redis.Redis.from_url(TEST_REDIS_URL, socket_connect_timeout=2) as client:
            client.ping()
    except redis.RedisError:
        return "no Redis answers at TEST_REDIS_URL"
    return None


# Checked once per test run. A Redis test file adds `needs_redis` to its pytestmark.
REDIS_SKIP_REASON = redis_skip_reason()
needs_redis = pytest.mark.skipif(REDIS_SKIP_REASON is not None, reason=str(REDIS_SKIP_REASON))

TEST_MINIO_ENDPOINT = os.environ.get("TEST_MINIO_ENDPOINT", "")


def minio_skip_reason() -> str | None:
    """Why the MinIO tests cannot run here, or None when they can."""
    if not TEST_MINIO_ENDPOINT:
        return "TEST_MINIO_ENDPOINT is not set"
    try:
        parts = TEST_MINIO_ENDPOINT.split(":", 1)
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 9000
        socket.create_connection((host, port), timeout=2).close()
    except (OSError, ValueError):
        return f"no MinIO answers at {TEST_MINIO_ENDPOINT}"
    return None


MINIO_SKIP_REASON = minio_skip_reason()


@contextmanager
def running_server(app: FastAPI) -> Iterator[str]:
    """Serve the app with uvicorn, as the container does, in a background thread, on a free
    local port. Yields its address ("127.0.0.1:<port>") for real HTTP and WebSocket clients.
    Two of these on the same database and Redis behave like two API workers."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))  # port 0: the system picks a free port
    host, port = listener.getsockname()
    server = uvicorn.Server(uvicorn.Config(app, log_config=None))  # keep our JSON logging
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "the test server did not start"
        time.sleep(0.01)
    try:
        yield f"{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


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


class FakeHealthSession:
    """Stands in for an active database session for tests that don't need real PostgreSQL."""

    async def execute(self, statement, *args, **kwargs):
        return None

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def refresh(self, instance, *args, **kwargs) -> None:
        pass

    async def flush(self) -> None:
        pass


class FakeHealthRedis:
    """Stands in for Redis for non-Redis tests, answering ping and heartbeat."""

    async def ping(self) -> bool:
        return True

    async def get(self, name: str) -> bytes | None:
        if name == "worker:heartbeat":
            return b"1"
        return None

    async def aclose(self) -> None:
        pass


class FakeHealthQueue:
    """Celery queue mock answering control inspect ping and tasks."""

    class _Celery:
        class _Control:
            class _Inspect:
                def ping(self):
                    return {"celery@test": {"ok": "pong"}}

            def inspect(self, timeout=None):
                return self._Inspect()

        def __init__(self):
            self.control = self._Control()

    def __init__(self):
        self.celery = self._Celery()

    def moderate_video(self, video_id: int, object_key: str) -> None:
        pass


def build_app(**overrides: object) -> FastAPI:
    """A fresh app for one test; keyword arguments change its settings, e.g. env="dev".

    The game scheduler (BE-27) is off unless a test turns it on (game_scheduler_enabled=True):
    only the game tests need its ticks, and every other app starts and stops faster without it.

    The email links and the public file URLs always start with https://localhost here,
    whatever FRONTEND_BASE_URL and MINIO_EXTERNAL_ENDPOINT the environment has (`make test`
    passes the ones from .env, e.g. https://localhost:18443).
    """
    settings = {
        "env": "prod",
        "internal_api_key": INTERNAL_KEY,
        "frontend_base_url": "https://localhost",
        "minio_external_endpoint": "https://localhost",
        "game_scheduler_enabled": False,
    }
    if "redis_url" not in overrides and TEST_REDIS_URL and REDIS_SKIP_REASON is None:
        settings["redis_url"] = TEST_REDIS_URL
    if (
        "minio_internal_endpoint" not in overrides
        and TEST_MINIO_ENDPOINT
        and MINIO_SKIP_REASON is None
    ):
        settings["minio_internal_endpoint"] = TEST_MINIO_ENDPOINT
    settings.update(overrides)

    app = create_app(Settings(**settings))
    # Real SMTP/Brevo tests instantiate Mailer directly. Route tests never send mail.
    mailbox = TestMailbox()
    app.state.test_mailbox = mailbox
    app.dependency_overrides[get_mailer] = lambda: mailbox

    # Default healthy stubs when running without real background services (BE-31)
    if DATABASE_SKIP_REASON is not None and "database_url" not in overrides:
        app.dependency_overrides.setdefault(get_session, lambda: FakeHealthSession())
    if (REDIS_SKIP_REASON is not None or not TEST_REDIS_URL) and "redis_url" not in overrides:
        app.dependency_overrides.setdefault(get_redis, lambda: FakeHealthRedis())
        app.dependency_overrides.setdefault(get_queue, lambda: FakeHealthQueue())
    if (
        MINIO_SKIP_REASON is not None or not TEST_MINIO_ENDPOINT
    ) and "minio_endpoint" not in overrides:
        app.state.storage.internal.bucket_exists = lambda bucket: True

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


def free_port() -> int:
    """A port number that nothing on this machine listens on right now."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SmtpInbox:
    """The test mail server calls handle_DATA for every email it receives; we keep them."""

    def __init__(self):
        self.emails = []

    async def handle_DATA(self, server, session, envelope):
        self.emails.append(message_from_bytes(envelope.content, policy=policy.default))
        return "250 OK"


@pytest.fixture
def smtp_server():
    """A real SMTP server on this machine (the aiosmtpd library), like Mailpit, for one test.
    Gives its port and its inbox."""
    inbox = SmtpInbox()
    server = Controller(inbox, hostname="127.0.0.1", port=free_port())
    server.start()
    yield server.port, inbox
    server.stop()


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
