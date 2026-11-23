"""Rate limits on the write routes (BE-12): every POST, PUT, PATCH and DELETE under /api, per
user when logged in and per IP otherwise, with a stricter number for some routes.

No database needed: the limit is checked before the route's own work, and the routes that must
succeed get a made-up user and a stand-in service. Counts start empty in every test (conftest).
"""

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import build_app
from fastapi.testclient import TestClient
from limits import parse

from app.auth import security
from app.auth.deps import get_current_user
from app.core import limiter
from app.core.limits import FRIEND_REQUEST_RATE_LIMIT, ROUTE_RATE_LIMITS, WRITE_RATE_LIMIT
from app.friends import service as friends_service
from app.users.models import User

FRIEND_REQUESTS = "/api/friends/requests"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """The app, where any token gets in as a made-up user and a friend request is "sent"
    without a database. The limiter still reads whose token it is."""
    app = build_app()
    app.dependency_overrides[get_current_user] = lambda: User(id=1, status="active")

    async def send_request(session, requester_id: int, addressee_id: int):
        return SimpleNamespace(
            id=1,
            requester_id=requester_id,
            addressee_id=addressee_id,
            status="pending",
            created_at=datetime.now(UTC),
        )

    monkeypatch.setattr(friends_service, "send_request", send_request)
    with TestClient(app) as test_client:
        yield test_client


def token_for(app, user_id: int, secret: str | None = None, minutes: int = 15) -> dict:
    """An Authorization header with an access token for this made-up user."""
    token, _ = security.create_token(
        secret or app.state.settings.jwt_secret,
        user_id,
        "access",
        timedelta(minutes=minutes),
        ver=0,
    )
    return {"Authorization": f"Bearer {token}"}


def amount(limit: str) -> int:
    return parse(limit).amount


def test_a_limited_route_answers_429_with_the_standard_body(client):
    alice = token_for(client.app, 10)
    for _ in range(amount(FRIEND_REQUEST_RATE_LIMIT)):
        response = client.post(FRIEND_REQUESTS, json={"addressee_id": 2}, headers=alice)
        assert response.status_code == 201, response.text
    response = client.post(FRIEND_REQUESTS, json={"addressee_id": 2}, headers=alice)
    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "429", "detail": "Rate limit exceeded: 10 per 1 minute"}
    }
    assert 1 <= int(response.headers["retry-after"]) <= 60  # seconds until the count restarts


def test_two_users_from_one_ip_have_their_own_counts(client):
    alice, bob = token_for(client.app, 10), token_for(client.app, 20)
    for _ in range(amount(FRIEND_REQUEST_RATE_LIMIT)):
        client.post(FRIEND_REQUESTS, json={"addressee_id": 2}, headers=alice)
    assert client.post(FRIEND_REQUESTS, json={"addressee_id": 2}, headers=alice).status_code == 429
    # Bob shares Alice's IP (same test client) but not her count.
    assert client.post(FRIEND_REQUESTS, json={"addressee_id": 2}, headers=bob).status_code == 201


def test_anonymous_writes_count_per_ip(client):
    first_browser = {"X-Real-IP": "203.0.113.1"}
    second_browser = {"X-Real-IP": "203.0.113.2"}
    for _ in range(amount(WRITE_RATE_LIMIT)):  # logout needs no login and no database
        assert client.post("/api/auth/logout", headers=first_browser).status_code == 204
    response = client.post("/api/auth/logout", headers=first_browser)
    assert response.status_code == 429
    assert response.json()["error"]["detail"] == "Rate limit exceeded: 60 per 1 minute"
    assert client.post("/api/auth/logout", headers=second_browser).status_code == 204


def test_a_made_up_or_expired_token_counts_for_its_ip(client, monkeypatch):
    """Inventing user ids must not give anyone a fresh count: only a token we signed, and
    still valid, counts for its user."""
    monkeypatch.setattr(limiter, "WRITE_RATE_LIMIT", "3/minute")
    same_browser = {"X-Real-IP": "203.0.113.9"}
    forged = [token_for(client.app, user_id, secret="x" * 40) for user_id in (1, 2)]
    expired = token_for(client.app, 3, minutes=-1)
    for headers in (*forged, expired):
        response = client.post("/api/auth/logout", headers={**same_browser, **headers})
        assert response.status_code == 204
    another_forged = token_for(client.app, 4, secret="y" * 40)
    response = client.post("/api/auth/logout", headers={**same_browser, **another_forged})
    assert response.status_code == 429
    # A real token from the same IP has its own count.
    response = client.post("/api/auth/logout", headers={**same_browser, **token_for(client.app, 5)})
    assert response.status_code == 204


def test_reads_are_never_counted(client, monkeypatch):
    monkeypatch.setattr(limiter, "WRITE_RATE_LIMIT", "1/minute")
    for _ in range(20):
        assert client.get("/api/media/avatar/default.svg").status_code == 200
    # The reads used none of the write count.
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/logout").status_code == 429
    assert client.get("/api/media/avatar/default.svg").status_code == 200


def write_operations(app) -> list[tuple[str, str]]:
    """Every (method, path) under /api that writes, from the app's OpenAPI description, with
    each {param} filled in with 1."""
    operations = []
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            if method.upper() in limiter.WRITE_METHODS and path.startswith("/api/"):
                operations.append((method.upper(), re.sub(r"\{[^}]+\}", "1", path)))
    return operations


def test_every_write_route_under_api_is_limited(client, monkeypatch):
    """Also covers the write routes added after BE-12: they get the default limit."""
    monkeypatch.setattr(limiter, "WRITE_RATE_LIMIT", "0/minute")  # the first request is over
    monkeypatch.setattr(limiter, "ROUTE_RATE_LIMITS", {})
    operations = write_operations(client.app)
    assert len(operations) > 40
    for method, path in operations:
        response = client.request(method, path)
        assert response.status_code == 429, f"{method} {path} is not limited"


def test_each_own_limit_reaches_its_route(client, monkeypatch):
    """Every line of ROUTE_RATE_LIMITS names a real route, written the way the limiter sees it
    (a typo or a renamed route would silently fall back to the default)."""
    monkeypatch.setattr(limiter, "WRITE_RATE_LIMIT", "1000/minute")
    monkeypatch.setattr(limiter, "ROUTE_RATE_LIMITS", dict.fromkeys(ROUTE_RATE_LIMITS, "0/minute"))
    for route in ROUTE_RATE_LIMITS:
        method, path = route.split(" ")
        response = client.request(method, "/api" + re.sub(r"\{[^}]+\}", "1", path))
        assert response.status_code == 429, f"{route} does not reach a route"
