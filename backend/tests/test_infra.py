"""Tests for backend test infrastructure (BE-20).

Verifies:
- TEST_DATABASE_URL environment configuration.
- Transactional rollback and commit-to-flush interception.
- Asynchronous test clients (`async_client` and `async_db_client`) with ASGITransport.
- Autouse external service mocks.
"""

from unittest.mock import AsyncMock, patch

import pytest
from conftest import TEST_DATABASE_URL
from sqlalchemy.ext.asyncio import AsyncSession


def test_test_database_url_is_configured():
    """TEST_DATABASE_URL is set and points to the designated test database."""
    assert TEST_DATABASE_URL
    assert "test" in TEST_DATABASE_URL.lower()


def test_autouse_external_service_mocks(mock_external_services):
    """External service mocks are initialized and active by default."""
    assert mock_external_services.ping() is True
    assert mock_external_services.presigned_put_external("sample.mp4") == "http://minio-fake/upload"
    assert (
        mock_external_services.presigned_get_external("sample.mp4") == "http://minio-fake/video.mp4"
    )


@pytest.mark.anyio
async def test_async_client_reaches_health_endpoint(async_client):
    """async_client interacts with FastAPI endpoints over ASGITransport."""
    response = await async_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # Verify x-request-id header injection still functions in async mode
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 32


@pytest.mark.anyio
async def test_async_client_carries_internal_key(async_client):
    """async_client includes default test credentials such as X-Internal-Key."""
    # /_internal/health/db returns 404 if key is wrong, but 503 or 200 if key is present
    response = await async_client.get("/_internal/health/db")
    assert response.status_code in (200, 503)
    assert response.status_code != 404


@pytest.mark.anyio
async def test_db_session_intercepts_commit_with_flush(db: AsyncSession):
    """In test sessions, commit() is intercepted to flush so uncommitted state stays isolated."""
    with patch.object(db, "flush", new_callable=AsyncMock) as mock_flush:
        await db.commit()
        assert mock_flush.await_count == 1


@pytest.mark.anyio
async def test_async_db_client_runs_with_db_session(async_db_client):
    """async_db_client executes requests with transactional session dependency injected."""
    response = await async_db_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sync_client_coexists_with_async_infrastructure(client):
    """Synchronous test client continues to function normally for non-db unit tests."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
