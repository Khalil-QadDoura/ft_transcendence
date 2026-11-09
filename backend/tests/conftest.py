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
from pathlib import Path

# Settings require DATABASE_URL and JWT_SECRET, and importing the app reads the settings.
# Made-up values, for tests only.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-0123456789abcdef")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.limiter import limiter
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
    """A fresh app for one test; keyword arguments change its settings, e.g. env="dev"."""
    settings = {"env": "prod", "internal_api_key": INTERNAL_KEY, **overrides}
    return create_app(Settings(**settings))


@pytest.fixture
def client():
    with TestClient(build_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Every test starts with empty rate limit counters."""
    limiter.reset()
