"""Shared test setup. No test needs a real database: the engine connects only on first query."""

import os

# Settings require DATABASE_URL, and importing the app reads the settings.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.limiter import limiter
from app.main import create_app

INTERNAL_KEY = "test-internal-key"


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
