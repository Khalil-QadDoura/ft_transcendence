"""Tests for the Prometheus /metrics endpoint and WebSocket connection gauge (BE-30)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import httpx2 as httpx
import pytest
import redis
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from websockets.sync.client import connect

from app.auth.security import hash_password
from app.core.metrics import track_ws_connection
from tests.conftest import (
    TEST_REDIS_URL,
    alembic,
    build_app,
    needs_database,
    needs_redis,
    running_server,
    sql,
)

PASSWORD = "TestPassword123!"
PASSWORD_HASH = hash_password(PASSWORD)


def _metric_samples(metrics_text: str, metric_name: str) -> list:
    """Return all Prometheus samples for `metric_name` parsed from /metrics text."""
    for family in text_string_to_metric_families(metrics_text):
        if family.name == metric_name:
            return list(family.samples)
    return []


def _find_sample_value(
    metrics_text: str,
    metric_name: str,
    required_labels: dict[str, str] | None = None,
) -> float | None:
    """Return the first matching sample value for `metric_name` and optional labels."""
    for sample in _metric_samples(metrics_text, metric_name):
        if required_labels is None or all(
            sample.labels.get(k) == v for k, v in required_labels.items()
        ):
            return sample.value
    return None


def _ws_connections_value(base_url: str) -> float | None:
    """Fetch `/metrics` from a running server and return the `ws_connections` gauge value."""
    response = httpx.get(f"{base_url}/metrics", timeout=5)
    assert response.status_code == 200
    return _find_sample_value(response.text, "ws_connections")


def _wait_for_ws_gauge(base_url: str, expected: float, timeout: float = 2.0) -> float | None:
    """Poll `/metrics` until `ws_connections` reaches `expected` or timeout elapses."""
    deadline = time.monotonic() + timeout
    value = _ws_connections_value(base_url)
    while value != expected and time.monotonic() < deadline:
        time.sleep(0.02)
        value = _ws_connections_value(base_url)
    return value


def test_metrics_endpoint_returns_prometheus_text_and_is_hidden_from_openapi(
    client: TestClient,
) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert _find_sample_value(response.text, "ws_connections") == 0.0

    openapi = client.get("/api/openapi.json")
    assert openapi.status_code == 200
    assert "/metrics" not in openapi.json()["paths"]


def test_metrics_records_routes_exact_status_codes_and_latency_excluding_self(
    client: TestClient,
) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/does-not-exist").status_code == 404

    # Scrape /metrics twice so self-requests would show up if /metrics were not excluded.
    first_scrape = client.get("/metrics")
    second_scrape = client.get("/metrics")
    assert first_scrape.status_code == 200
    assert second_scrape.status_code == 200

    body = second_scrape.text
    assert (
        _find_sample_value(
            body,
            "http_requests",
            {"handler": "/api/health", "method": "GET", "status": "200"},
        )
        == 1.0
    )
    assert _find_sample_value(body, "http_requests", {"status": "404"}) == 1.0
    assert (
        _find_sample_value(
            body,
            "http_request_duration_seconds",
            {"handler": "/api/health", "method": "GET"},
        )
        is not None
    )

    samples = _metric_samples(body, "http_requests")
    assert all(sample.labels.get("handler") != "/metrics" for sample in samples)


def test_metrics_registries_are_isolated_across_app_instances() -> None:
    app_one = build_app()
    app_two = build_app()

    with TestClient(app_one) as client_one, TestClient(app_two) as client_two:
        assert client_one.get("/api/health").status_code == 200
        assert client_one.get("/api/health").status_code == 200

        metrics_one = client_one.get("/metrics").text
        metrics_two = client_two.get("/metrics").text

    assert (
        _find_sample_value(
            metrics_one,
            "http_requests",
            {"handler": "/api/health", "method": "GET", "status": "200"},
        )
        == 2.0
    )
    assert (
        _find_sample_value(
            metrics_two,
            "http_requests",
            {"handler": "/api/health", "method": "GET", "status": "200"},
        )
        is None
    )


def test_track_ws_connection_updates_gauge_and_recovers_on_error() -> None:
    app = build_app()

    async def exercise() -> float | None:
        async with track_ws_connection(app):
            with TestClient(app) as client:
                return _find_sample_value(client.get("/metrics").text, "ws_connections")

    assert asyncio.run(exercise()) == 1.0
    with TestClient(app) as client:
        assert _find_sample_value(client.get("/metrics").text, "ws_connections") == 0.0

    async def fail_inside() -> None:
        async with track_ws_connection(app):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(fail_inside())

    with TestClient(app) as client:
        assert _find_sample_value(client.get("/metrics").text, "ws_connections") == 0.0


@pytest.fixture
def metrics_live_server() -> Iterator[str]:
    """Start a real server backed by Postgres + Redis and clean only `ws:*` + `users` state."""
    alembic("upgrade", "head")
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    redis_client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    for key in redis_client.scan_iter("ws:*"):
        redis_client.delete(key)

    app = build_app()
    try:
        with running_server(app) as host_port:
            yield host_port
    finally:
        sql("TRUNCATE users RESTART IDENTITY CASCADE")
        for key in redis_client.scan_iter("ws:*"):
            redis_client.delete(key)
        redis_client.close()


def _create_verified_user_and_get_ticket(host_port: str, email: str, client_ip: str) -> str:
    """Insert a verified user, log in, and exchange the access token for a WS ticket."""
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :password_hash, TRUE)",
        email=email,
        password_hash=PASSWORD_HASH,
    )
    login = httpx.post(
        f"http://{host_port}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"X-Real-IP": client_ip},
        timeout=5,
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]

    ticket_resp = httpx.post(
        f"http://{host_port}/api/ws/ticket",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=5,
    )
    assert ticket_resp.status_code == 201
    return ticket_resp.json()["ticket"]


@needs_database
@needs_redis
def test_ws_connections_gauge_tracks_open_and_closed_websockets(metrics_live_server: str) -> None:
    base_url = f"http://{metrics_live_server}"
    assert _ws_connections_value(base_url) == 0.0

    ticket_one = _create_verified_user_and_get_ticket(
        metrics_live_server, "ws-metrics-1@example.com", "10.30.0.1"
    )
    ticket_two = _create_verified_user_and_get_ticket(
        metrics_live_server, "ws-metrics-2@example.com", "10.30.0.2"
    )

    with connect(f"ws://{metrics_live_server}/ws?ticket={ticket_one}", open_timeout=5):
        assert _wait_for_ws_gauge(base_url, 1.0) == 1.0

        with connect(f"ws://{metrics_live_server}/ws?ticket={ticket_two}", open_timeout=5):
            assert _wait_for_ws_gauge(base_url, 2.0) == 2.0

        assert _wait_for_ws_gauge(base_url, 1.0) == 1.0

    assert _wait_for_ws_gauge(base_url, 0.0) == 0.0
