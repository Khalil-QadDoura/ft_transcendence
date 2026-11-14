"""GET /api/health with per-component checks and /_internal/health/db (BE-31)."""

import asyncio
import time

from conftest import (
    INTERNAL_KEY,
    TEST_DATABASE_URL,
    TEST_REDIS_URL,
    build_app,
    needs_database,
    needs_redis,
)
from fastapi.testclient import TestClient

from app.core.queue import get_queue
from app.core.redis_client import get_redis
from app.core.storage import get_storage
from app.db.session import get_session

KEY = {"X-Internal-Key": INTERNAL_KEY}


class MockSession:
    """Mock database session supporting success, failures, and artificial delay."""

    def __init__(self, fails: bool = False, delay: float = 0.0):
        self.fails = fails
        self.delay = delay

    async def execute(self, statement, *args, **kwargs):
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.fails:
            raise ConnectionRefusedError("database is down")
        return None


class MockRedis:
    """Mock Redis client supporting ping, heartbeat key, failure, and delay."""

    def __init__(
        self,
        ping_ok: bool = True,
        heartbeat: bytes | None = b"1",
        delay: float = 0.0,
    ):
        self.ping_ok = ping_ok
        self.heartbeat = heartbeat
        self.delay = delay

    async def ping(self) -> bool:
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if not self.ping_ok:
            raise ConnectionRefusedError("redis is down")
        return True

    async def get(self, name: str) -> bytes | None:
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if not self.ping_ok:
            raise ConnectionRefusedError("redis is down")
        if name == "worker:heartbeat":
            return self.heartbeat
        return None

    async def aclose(self) -> None:
        pass


class MockStorage:
    """Mock MinIO Storage supporting bucket check, failure, and delay."""

    class _Internal:
        def __init__(self, exists: bool = True, raises: bool = False, delay: float = 0.0):
            self.exists = exists
            self.raises = raises
            self.delay = delay

        def bucket_exists(self, bucket_name: str) -> bool:
            if self.delay > 0:
                time.sleep(self.delay)
            if self.raises:
                raise RuntimeError("minio connection lost")
            return self.exists

    def __init__(self, exists: bool = True, raises: bool = False, delay: float = 0.0):
        self.bucket = "wozu-media"
        self.internal = self._Internal(exists=exists, raises=raises, delay=delay)


class MockQueue:
    """Mock TaskQueue and Celery inspect for worker checks."""

    class _Inspect:
        def __init__(
            self,
            ping_res: dict | None = None,
            raises: bool = False,
            delay: float = 0.0,
        ):
            self.ping_res = ping_res
            self.raises = raises
            self.delay = delay

        def ping(self):
            if self.delay > 0:
                time.sleep(self.delay)
            if self.raises:
                raise RuntimeError("celery inspect failure")
            return self.ping_res

    class _Control:
        def __init__(self, inspect_obj):
            self._inspect_obj = inspect_obj

        def inspect(self, timeout=None):
            return self._inspect_obj

    class _Celery:
        def __init__(self, inspect_obj):
            self.control = MockQueue._Control(inspect_obj)

    def __init__(
        self,
        ping_res: dict | None = None,
        raises: bool = False,
        delay: float = 0.0,
    ):
        inspect_obj = self._Inspect(ping_res=ping_res, raises=raises, delay=delay)
        self.celery = self._Celery(inspect_obj)


def test_health_all_components_ok_returns_200(client):
    """When DB, Redis, MinIO, and Celery worker are all up, overall status is 'ok' (HTTP 200)."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {
            "db": "ok",
            "redis": "ok",
            "minio": "ok",
            "worker": "ok",
        },
    }


def test_health_auxiliary_worker_down_returns_200_degraded(client):
    """When worker is down but core (db, redis) and minio are up: status 'degraded' (HTTP 200)."""
    client.app.dependency_overrides[get_queue] = lambda: MockQueue(ping_res=None)
    client.app.dependency_overrides[get_redis] = lambda: MockRedis(heartbeat=None)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "components": {
            "db": "ok",
            "redis": "ok",
            "minio": "ok",
            "worker": "down",
        },
    }


def test_health_auxiliary_minio_down_returns_200_degraded(client):
    """When minio is down but core (db, redis) and worker are up: status 'degraded' (HTTP 200)."""
    client.app.dependency_overrides[get_storage] = lambda: MockStorage(raises=True)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "components": {
            "db": "ok",
            "redis": "ok",
            "minio": "down",
            "worker": "ok",
        },
    }


def test_health_core_redis_down_returns_503_down(client):
    """When Redis is down: status 'down' (HTTP 503)."""
    client.app.dependency_overrides[get_redis] = lambda: MockRedis(ping_ok=False)
    response = client.get("/api/health")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "down"
    assert payload["components"]["redis"] == "down"


def test_health_core_db_down_returns_503_down(client):
    """When PostgreSQL is down: status 'down' (HTTP 503)."""
    client.app.dependency_overrides[get_session] = lambda: MockSession(fails=True)
    response = client.get("/api/health")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "down"
    assert payload["components"]["db"] == "down"


def test_health_multiple_components_down_returns_503_down(client):
    """When both core (db) and auxiliary (worker) are down: status 'down' (HTTP 503)."""
    client.app.dependency_overrides[get_session] = lambda: MockSession(fails=True)
    client.app.dependency_overrides[get_queue] = lambda: MockQueue(ping_res=None)
    client.app.dependency_overrides[get_redis] = lambda: MockRedis(heartbeat=None)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "down",
        "components": {
            "db": "down",
            "redis": "ok",
            "minio": "ok",
            "worker": "down",
        },
    }


def test_health_probe_timeout_bounded(client):
    """Slow component probes timeout within 1.0s and overall check finishes promptly."""
    client.app.dependency_overrides[get_session] = lambda: MockSession(delay=1.5)
    start = time.perf_counter()
    response = client.get("/api/health")
    duration = time.perf_counter() - start

    assert duration < 1.4, f"Probe took {duration:.2f}s, exceeding bounded timeout"
    assert response.status_code == 503
    assert response.json()["components"]["db"] == "down"


def test_health_no_leaked_secrets_or_hostnames(client):
    """Ensure hostnames, worker node ids, and internal credentials are never exposed."""
    secret_host = "worker-node-42.internal.cluster.priv"
    secret_token = "ultra-secret-key-xyz"
    client.app.dependency_overrides[get_queue] = lambda: MockQueue(
        ping_res={f"celery@{secret_host}": {"ok": secret_token}}
    )
    client.app.dependency_overrides[get_redis] = lambda: MockRedis(heartbeat=None)

    response = client.get("/api/health")
    assert response.status_code == 200
    assert secret_host not in response.text
    assert secret_token not in response.text
    assert "celery@" not in response.text


def test_health_worker_heartbeat_fast_path(client):
    """Worker heartbeat in Redis marks worker ok without calling Celery inspect."""
    # Mock inspect raises RuntimeError, proving it was never called
    client.app.dependency_overrides[get_queue] = lambda: MockQueue(raises=True)
    client.app.dependency_overrides[get_redis] = lambda: MockRedis(heartbeat=b"active")

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["components"]["worker"] == "ok"


def test_health_worker_celery_inspect_fallback(client):
    """When heartbeat key is absent, Celery inspect ping is used as fallback."""
    client.app.dependency_overrides[get_queue] = lambda: MockQueue(
        ping_res={"celery@worker": {"ok": "pong"}}
    )
    client.app.dependency_overrides[get_redis] = lambda: MockRedis(heartbeat=None)

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["components"]["worker"] == "ok"


def test_health_worker_both_fail(client):
    """When both heartbeat and Celery inspect fail, worker is down."""
    client.app.dependency_overrides[get_queue] = lambda: MockQueue(raises=True)
    client.app.dependency_overrides[get_redis] = lambda: MockRedis(heartbeat=None)

    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["components"]["worker"] == "down"


def test_internal_route_without_key_is_404(client):
    assert client.get("/_internal/health/db").status_code == 404
    wrong = client.get("/_internal/health/db", headers={"X-Internal-Key": "guess"})
    assert wrong.status_code == 404
    assert wrong.json() == {"error": {"code": "404", "detail": "Not Found"}}


def test_internal_routes_closed_when_no_key_is_configured():
    with TestClient(build_app(internal_api_key="")) as client:
        response = client.get("/_internal/health/db", headers={"X-Internal-Key": ""})
    assert response.status_code == 404


def test_internal_database_check_with_key(client):
    client.app.dependency_overrides[get_session] = lambda: MockSession()
    response = client.get("/_internal/health/db", headers=KEY)
    assert response.status_code == 200
    assert response.json() == {"database": "ok"}


def test_internal_database_check_reports_a_down_database(client):
    client.app.dependency_overrides[get_session] = lambda: MockSession(fails=True)
    response = client.get("/_internal/health/db", headers=KEY)
    assert response.status_code == 503
    assert response.json() == {"database": "unreachable"}


@needs_database
@needs_redis
def test_health_with_real_database_and_redis():
    """Integration check when live PostgreSQL and Redis test containers are available."""
    app = build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    with TestClient(app) as test_client:
        response = test_client.get("/api/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["components"]["db"] == "ok"
        assert payload["components"]["redis"] == "ok"
