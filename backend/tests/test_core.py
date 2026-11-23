"""Error body, request id, JSON logs and the rate limiter."""

import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from conftest import build_app
from fastapi import APIRouter, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.limiter import limiter
from app.core.logging import json_handler

# Routes that exist only in tests, to trigger each kind of error.
extra_routes = APIRouter(prefix="/api/test")


class Item(BaseModel):
    name: str
    price: int


@extra_routes.get("/conflict")
def conflict():
    raise HTTPException(status_code=409, detail="Already exists")


@extra_routes.post("/items")
def create_item(item: Item):
    return item


@extra_routes.get("/limited")
@limiter.limit("2/minute")
def limited(request: Request):
    return {"ok": True}


@extra_routes.get("/crash")
def crash():
    raise RuntimeError("secret internals")


def add_extra_routes(app):
    app.include_router(extra_routes)


@contextmanager
def captured_logs() -> Iterator[list[dict]]:
    """Collects the JSON log lines written inside the `with` block, as dicts."""
    stream = io.StringIO()
    handler = json_handler(stream)
    logging.getLogger().addHandler(handler)
    lines: list[dict] = []
    try:
        yield lines
    finally:
        logging.getLogger().removeHandler(handler)
        lines.extend(json.loads(line) for line in stream.getvalue().splitlines())


def test_http_error_uses_the_error_body(client):
    add_extra_routes(client.app)
    response = client.get("/api/test/conflict")
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "409", "detail": "Already exists"}}


def test_unknown_route_uses_the_error_body(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "404", "detail": "Not Found"}}


def test_validation_error_returns_only_the_first_failing_field(client):
    add_extra_routes(client.app)
    # Both fields are wrong; only the first one (name) is reported.
    response = client.post("/api/test/items", json={"price": "not a number"})
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "422", "detail": "body → name: Field required"}}


def test_unexpected_error_hides_internals_but_keeps_the_request_id():
    app = build_app()
    add_extra_routes(app)
    # By default the test client re-raises server errors; here we want the 500 response.
    with TestClient(app, raise_server_exceptions=False) as client, captured_logs() as logs:
        response = client.get("/api/test/crash", headers={"x-request-id": "crash-1"})
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "500", "detail": "Internal server error"}}
    assert response.headers["x-request-id"] == "crash-1"
    # The server log has the 500 "request" line and the traceback, both with the same id.
    request_line = next(line for line in logs if line["event"] == "request")
    assert request_line["request_id"] == "crash-1"
    assert request_line["status"] == 500
    error_line = next(line for line in logs if "exception" in line)
    assert error_line["request_id"] == "crash-1"
    assert "secret internals" in error_line["exception"]


def test_rate_limiter_returns_429_with_the_error_body(client):
    add_extra_routes(client.app)
    assert client.get("/api/test/limited").status_code == 200
    assert client.get("/api/test/limited").status_code == 200
    response = client.get("/api/test/limited")
    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "429", "detail": "Rate limit exceeded: 2 per 1 minute"}
    }
    assert 1 <= int(response.headers["retry-after"]) <= 60  # seconds until the count restarts


def test_rate_limits_count_each_client_ip_separately(client):
    add_extra_routes(client.app)
    first_browser = {"X-Real-IP": "203.0.113.1"}
    second_browser = {"X-Real-IP": "203.0.113.2"}
    for _ in range(2):
        assert client.get("/api/test/limited", headers=first_browser).status_code == 200
    assert client.get("/api/test/limited", headers=first_browser).status_code == 429
    assert client.get("/api/test/limited", headers=second_browser).status_code == 200


def test_every_response_gets_a_request_id(client):
    response = client.get("/api/health")
    assert len(response.headers["x-request-id"]) == 32


def test_request_id_from_the_caller_is_kept(client):
    response = client.get("/api/health", headers={"x-request-id": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


def test_request_log_line_is_json_with_the_request_id(client):
    with captured_logs() as logs:
        client.get("/api/health", headers={"x-request-id": "abc-123"})
    request_line = next(line for line in logs if line["event"] == "request")
    assert request_line["request_id"] == "abc-123"
    assert request_line["path"] == "/api/health"
    assert request_line["status"] == 200
