"""Route inventory (BE-13): every HTTP and WebSocket route of the app needs a login, unless it
is on the public list below, with the reason why it is public.

The routes come from the app itself: every router, also the routes hidden from the OpenAPI page
(/_internal, /metrics) and the two WebSockets. So a route added later is checked the day it is
added: if it has no login check and no line here, this test fails.

Each protected route is called with no token and with eight kinds of bad token, and must answer
401 every time. Then a valid token must get past the login check (anything but 401), which shows
that the 401s came from the login check and not from something else. On a real database and a
real Redis; the users are made up.
"""

import re
import uuid
from datetime import timedelta

import httpx2
import jwt
import pytest
from conftest import (
    INTERNAL_KEY,
    TEST_DATABASE_URL,
    TEST_REDIS_URL,
    alembic,
    build_app,
    needs_database,
    needs_redis,
    running_server,
    sql,
)
from fastapi.routing import iter_route_contexts
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from app.auth import security
from app.auth.constants import ACCESS_SCOPE, REFRESH_SCOPE

pytestmark = [needs_database, needs_redis]

# The routes anyone may call without logging in, and why. Every other route needs a valid
# access token (or, for a WebSocket, a ticket that only a logged-in user can get).
PUBLIC = {
    # Up / down, per component, for the proxy, Docker and the status page; no user data.
    "GET /api/health",
    # The API's description; the contract lists it as public (System). The Swagger page and its
    # helper exist only with ENV=dev (the defense's .env).
    "GET /api/openapi.json",
    "GET /api/docs",
    "GET /api/docs/oauth2-redirect",
    # Sign-up, login and passwords: whoever calls them has no access token yet.
    "POST /api/auth/register",
    "GET /api/auth/verify",
    "POST /api/auth/login",
    "POST /api/auth/refresh",
    "POST /api/auth/logout",
    "POST /api/auth/forgot-password",
    "POST /api/auth/reset-password",
    # Login with 42: the button opens the first, and 42's page sends the browser to the second.
    "GET /api/auth/oauth/42/start",
    "GET /api/auth/oauth/42/callback",
    # The job search and a job's page can be seen before logging in (contract: "—", "optional").
    # With a token they know the reader (the owner sees a draft); a bad token is still 401.
    "GET /api/jobs/open",
    "GET /api/jobs/{job_id}",
    "POST /api/jobs/{job_id}/view",
    # The grey picture of a user without an avatar, for <img> tags.
    "GET /api/media/avatar/default.svg",
    # Prometheus reads it inside the Docker network; outside, the proxy answers 404 for it.
    "GET /metrics",
}

# Closed by the internal key (X-Internal-Key), not by a user login: 404 without it.
INTERNAL_PREFIX = "/_internal/"

WAIT = 5  # seconds to wait for a socket to be closed


def all_routes(app) -> list[str]:
    """Every route of the app as "METHOD /path", and "WS /path" for a WebSocket. The same walk
    over all routers that FastAPI's own OpenAPI page makes, without leaving any route out."""
    routes = []
    for route in iter_route_contexts(app.routes):
        if route.methods is None:  # a WebSocket has no HTTP method
            routes.append(f"WS {route.path}")
        else:
            routes += [f"{method} {route.path}" for method in route.methods - {"HEAD"}]
    return sorted(routes)


def filled(path: str) -> str:
    """The path with every {param} written as 1, e.g. /api/jobs/1."""
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


@pytest.fixture(scope="module")
def app():
    # ENV=dev, as in the defense's .env: the most routes (the Swagger page too).
    return build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL, env="dev")


def new_user(email: str) -> int:
    [(user_id,)] = sql(
        "INSERT INTO users (email, is_email_verified) VALUES (:email, true) RETURNING id",
        email=email,
    )
    return user_id


def access_token(app, user_id: int, **changes) -> str:
    """An access token of ours for this user, as login makes it (token_version 1)."""
    settings = app.state.settings
    secret = changes.pop("secret", settings.jwt_secret)
    lifetime = changes.pop("lifetime", timedelta(minutes=15))
    scope = changes.pop("scope", ACCESS_SCOPE)
    token, _ = security.create_token(secret, user_id, scope, lifetime, **{"ver": 1, **changes})
    return token


def bad_credentials(app, user_id: int, deleted_id: int) -> dict[str, dict]:
    """Every kind of Authorization header that must not open a protected route."""
    unsigned = jwt.encode(
        {"sub": str(user_id), "scope": ACCESS_SCOPE, "jti": uuid.uuid4().hex, "ver": 1},
        key=None,
        algorithm="none",
    )
    bearer = {
        "a made-up token": "not.a.token",
        "a token signed with another key": access_token(app, user_id, secret="x" * 40),
        "an expired token": access_token(app, user_id, lifetime=timedelta(seconds=-1)),
        "a refresh token": access_token(app, user_id, scope=REFRESH_SCOPE),
        "a token from before a password change": access_token(app, user_id, ver=0),
        "an unsigned token (alg none)": unsigned,
        "a token of a deleted account": access_token(app, deleted_id),
    }
    return {
        "no token": {},
        "another scheme": {"Authorization": "Basic YW5hOnNlY3JldA=="},
        **{name: {"Authorization": f"Bearer {token}"} for name, token in bearer.items()},
    }


def test_every_public_route_exists(app):
    """No stale line: a public route that was renamed or removed must leave this list too."""
    assert PUBLIC <= set(all_routes(app))


def test_every_route_needs_a_login_unless_it_is_public(app):
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    user_id = new_user("ana@example.com")
    deleted_id = new_user("gone@example.com")
    sql("UPDATE users SET status = 'deleted' WHERE id = :id", id=deleted_id)
    credentials = bad_credentials(app, user_id, deleted_id)
    checked = []
    with running_server(app) as server:
        for route in all_routes(app):
            method, path = route.split(" ", 1)
            if route in PUBLIC or method == "WS":
                continue  # the sockets have their own test below
            url = f"http://{server}{filled(path)}"
            if path.startswith(INTERNAL_PREFIX):
                for headers in ({}, {"X-Internal-Key": "wrong"}):
                    response = httpx2.request(method, url, headers=headers)
                    assert response.status_code == 404, route
                continue
            for name, headers in credentials.items():
                response = httpx2.request(method, url, headers=headers)
                assert response.status_code == 401, f"{route} with {name}: {response.text}"
                assert response.headers["www-authenticate"] == "Bearer", route
            # A valid token gets past the login check: so the 401s above came from it. Each
            # route gets its own new user, so that DELETE /api/users/me hurts nobody else.
            owner = new_user(f"{uuid.uuid4().hex}@example.com")
            valid = {"Authorization": f"Bearer {access_token(app, owner)}"}
            response = httpx2.request(method, url, headers=valid)
            assert response.status_code != 401, f"{route} refuses a valid token"
            checked.append(route)
    assert len(checked) > 50  # every protected HTTP route of the app, not just a few


def test_every_websocket_needs_a_ticket(app):
    """A WebSocket opens only with a one-time ticket from POST /api/ws/ticket, which needs a
    login. No ticket, or a made-up one, is closed with 1008."""
    sockets = [route.split(" ", 1)[1] for route in all_routes(app) if route.startswith("WS ")]
    assert sockets == ["/ws", "/ws/game"]
    with running_server(app) as server:
        for path in sockets:
            for query in ("", "?ticket=", "?ticket=made-up", "?ticket=x&room_id=1"):
                with connect(f"ws://{server}{path}{query}", open_timeout=WAIT) as ws:
                    with pytest.raises(ConnectionClosed):
                        ws.recv(timeout=WAIT)
                    assert ws.close_code == 1008, f"{path}{query}"


def test_the_public_routes_answer_without_a_login(app):
    """What the list says: these work without a token (no 401)."""
    with running_server(app) as server:
        for route in sorted(PUBLIC):
            method, path = route.split(" ", 1)
            response = httpx2.request(method, f"http://{server}{filled(path)}")
            assert response.status_code != 401, route


def test_the_internal_routes_open_only_with_the_internal_key(app):
    with running_server(app) as server:
        response = httpx2.get(
            f"http://{server}/_internal/health/db", headers={"X-Internal-Key": INTERNAL_KEY}
        )
    assert response.status_code == 200
