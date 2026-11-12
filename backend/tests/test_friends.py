"""Tests for friends domain, public profiles, Redis presence, and BE-22 requirements."""

import asyncio
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx2
import redis
from conftest import (
    TEST_DATABASE_URL,
    TEST_REDIS_URL,
    alembic,
    build_app,
    needs_database,
    needs_redis,
    running_server,
    sql,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from websockets.sync.client import connect as ws_connect

from app.auth import security
from app.auth.deps import get_current_user
from app.friends import service as friends_service
from app.friends.models import Friendship
from app.users.models import User

AUTH_SECRET = "test-only-jwt-secret-0123456789abcdef"
USER_A = User(id=10, email="alice@example.com", status="active", token_version=1)
USER_B = User(id=20, email="bob@example.com", status="active", token_version=1)
USER_C = User(id=30, email="charlie@example.com", status="active", token_version=1)

TOKEN_A, _ = security.create_token(
    AUTH_SECRET, user_id=10, scope="access", lifetime=timedelta(minutes=15), ver=1
)
TOKEN_B, _ = security.create_token(
    AUTH_SECRET, user_id=20, scope="access", lifetime=timedelta(minutes=15), ver=1
)

AUTH_HEADER_A = {"Authorization": f"Bearer {TOKEN_A}"}
AUTH_HEADER_B = {"Authorization": f"Bearer {TOKEN_B}"}


def _fake_user(
    id: int = 20,
    first_name: str = "Bob",
    last_name: str = "Builder",
    position: str = "Chef",
    bio: str = "Hello!",
    avatar_object_key: str | None = None,
    status: str = "active",
) -> User:
    u = User(
        id=id,
        email=f"u{id}@example.com",
        first_name=first_name,
        last_name=last_name,
        position=position,
        bio=bio,
        avatar_object_key=avatar_object_key,
        status=status,
        token_version=1,
        is_email_verified=True,
    )
    return u


def _fake_friendship(
    id: int = 1,
    requester_id: int = 10,
    addressee_id: int = 20,
    status: str = "pending",
) -> Friendship:
    now = datetime.now(UTC)
    f = Friendship(id=id, requester_id=requester_id, addressee_id=addressee_id, status=status)
    f.created_at = now
    f.updated_at = now
    return f


# ── Auth & Validation Unit Tests ──────────────────────────────────────────────


def test_unauthenticated_requests_return_401(client):
    """Every friends/profile endpoint rejects unauthenticated requests with 401."""
    for method, path, kwargs in [
        ("POST", "/api/friends/requests", {"json": {"addressee_id": 20}}),
        ("GET", "/api/friends/requests", {}),
        ("POST", "/api/friends/requests/1/accept", {}),
        ("POST", "/api/friends/requests/1/decline", {}),
        ("DELETE", "/api/friends/1", {}),
        ("GET", "/api/friends", {}),
        ("GET", "/api/users/20/profile", {}),
    ]:
        resp = getattr(client, method.lower())(path, **kwargs)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"
        assert resp.json()["error"]["detail"] == "Not authenticated"


def test_invalid_tokens_return_401(client):
    """Malformed or expired JWTs return 401."""
    resp = client.get("/api/friends", headers={"Authorization": "Bearer 99"})
    assert resp.status_code == 401
    assert resp.json()["error"]["detail"] == "Invalid or expired token"

    expired, _ = security.create_token(
        AUTH_SECRET, user_id=10, scope="access", lifetime=timedelta(seconds=-5), ver=1
    )
    resp2 = client.get("/api/users/20/profile", headers={"Authorization": f"Bearer {expired}"})
    assert resp2.status_code == 401


def test_out_of_range_ids_return_422(client):
    """Negative, zero, or >BIGINT ids fail validation with 422 before hitting DB."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    too_big = 2**63
    for bad in (0, -1, too_big):
        assert (
            client.post(
                "/api/friends/requests", json={"addressee_id": bad}, headers=AUTH_HEADER_A
            ).status_code
            == 422
        )
        assert (
            client.post(f"/api/friends/requests/{bad}/accept", headers=AUTH_HEADER_A).status_code
            == 422
        )
        assert (
            client.post(f"/api/friends/requests/{bad}/decline", headers=AUTH_HEADER_A).status_code
            == 422
        )
        assert client.delete(f"/api/friends/{bad}", headers=AUTH_HEADER_A).status_code == 422
        assert client.get(f"/api/users/{bad}/profile", headers=AUTH_HEADER_A).status_code == 422


# ── Friend Request Lifecycle Unit Tests ───────────────────────────────────────


def test_send_friend_request_errors_and_success(client):
    """Validates self-request (400), missing user (404), duplicate (409), and creation (201)."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A

    # Self request -> 400
    r_self = client.post(
        "/api/friends/requests", json={"addressee_id": USER_A.id}, headers=AUTH_HEADER_A
    )
    assert r_self.status_code == 400

    # Missing or deleted addressee -> 404
    with patch("app.friends.repo.get_active_user", new_callable=AsyncMock, return_value=None):
        r_missing = client.post(
            "/api/friends/requests", json={"addressee_id": 20}, headers=AUTH_HEADER_A
        )
    assert r_missing.status_code == 404

    # Existing pending or accepted -> 409
    for existing_status in ("pending", "accepted"):
        with (
            patch(
                "app.friends.repo.get_active_user",
                new_callable=AsyncMock,
                return_value=_fake_user(20),
            ),
            patch(
                "app.friends.repo.get_live_friendship_for_pair",
                new_callable=AsyncMock,
                return_value=_fake_friendship(status=existing_status),
            ),
        ):
            r_dup = client.post(
                "/api/friends/requests", json={"addressee_id": 20}, headers=AUTH_HEADER_A
            )
        assert r_dup.status_code == 409

    # Success -> 201
    created = _fake_friendship(id=5, requester_id=10, addressee_id=20, status="pending")
    with (
        patch(
            "app.friends.repo.get_active_user", new_callable=AsyncMock, return_value=_fake_user(20)
        ),
        patch(
            "app.friends.repo.get_live_friendship_for_pair",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.friends.repo.create_friend_request", new_callable=AsyncMock, return_value=created
        ),
    ):
        r_ok = client.post(
            "/api/friends/requests", json={"addressee_id": 20}, headers=AUTH_HEADER_A
        )
    assert r_ok.status_code == 201
    assert r_ok.json()["id"] == 5
    assert r_ok.json()["status"] == "pending"


def test_send_request_integrity_error_returns_409():
    """Concurrent unique constraint violation rolls back cleanly and returns 409."""
    mock_session = AsyncMock()

    async def run():
        with (
            patch(
                "app.friends.repo.get_active_user",
                new_callable=AsyncMock,
                return_value=_fake_user(20),
            ),
            patch(
                "app.friends.repo.get_live_friendship_for_pair",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.friends.repo.create_friend_request",
                new_callable=AsyncMock,
                side_effect=IntegrityError("INSERT", {}, Exception("uq_friendships_pair")),
            ),
        ):
            try:
                await friends_service.send_request(mock_session, requester_id=10, addressee_id=20)
            except HTTPException as exc:
                return exc
        return None

    exc = asyncio.run(run())
    assert exc is not None
    assert exc.status_code == 409
    mock_session.rollback.assert_awaited_once()


def test_list_incoming_requests(client):
    """GET /api/friends/requests returns incoming pending rows."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_B
    pending = _fake_friendship(id=8, requester_id=10, addressee_id=20, status="pending")
    with patch(
        "app.friends.repo.list_incoming_requests", new_callable=AsyncMock, return_value=[pending]
    ):
        resp = client.get("/api/friends/requests", headers=AUTH_HEADER_B)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["requester_id"] == 10
    assert resp.json()[0]["status"] == "pending"


def test_accept_and_decline_request_rules(client):
    """Only the addressee can accept/decline pending requests (403/404/409/200)."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_B

    for action in ("accept", "decline"):
        with patch(
            "app.friends.repo.get_friendship_by_id", new_callable=AsyncMock, return_value=None
        ):
            assert (
                client.post(f"/api/friends/requests/1/{action}", headers=AUTH_HEADER_B).status_code
                == 404
            )

        # Requester or outsider cannot accept/decline, even if already non-pending
        other_row = _fake_friendship(id=1, requester_id=20, addressee_id=30, status="accepted")
        with patch(
            "app.friends.repo.get_friendship_by_id", new_callable=AsyncMock, return_value=other_row
        ):
            assert (
                client.post(f"/api/friends/requests/1/{action}", headers=AUTH_HEADER_B).status_code
                == 403
            )

        # Already accepted/declined -> 409
        not_pending = _fake_friendship(id=1, requester_id=10, addressee_id=20, status="accepted")
        with patch(
            "app.friends.repo.get_friendship_by_id",
            new_callable=AsyncMock,
            return_value=not_pending,
        ):
            assert (
                client.post(f"/api/friends/requests/1/{action}", headers=AUTH_HEADER_B).status_code
                == 409
            )

    # Deleted requester when accepting -> 404
    pending = _fake_friendship(id=1, requester_id=10, addressee_id=20, status="pending")
    with (
        patch(
            "app.friends.repo.get_friendship_by_id", new_callable=AsyncMock, return_value=pending
        ),
        patch("app.friends.repo.get_active_user", new_callable=AsyncMock, return_value=None),
    ):
        assert (
            client.post("/api/friends/requests/1/accept", headers=AUTH_HEADER_B).status_code == 404
        )

    # Success accept and decline
    for action, expected in (("accept", "accepted"), ("decline", "declined")):
        row = _fake_friendship(id=1, requester_id=10, addressee_id=20, status="pending")
        updated = _fake_friendship(id=1, requester_id=10, addressee_id=20, status=expected)
        with (
            patch(
                "app.friends.repo.get_friendship_by_id", new_callable=AsyncMock, return_value=row
            ),
            patch(
                "app.friends.repo.get_active_user",
                new_callable=AsyncMock,
                return_value=_fake_user(10),
            ),
            patch(
                "app.friends.repo.set_friendship_status",
                new_callable=AsyncMock,
                return_value=updated,
            ),
        ):
            resp = client.post(f"/api/friends/requests/1/{action}", headers=AUTH_HEADER_B)
        assert resp.status_code == 200
        assert resp.json()["status"] == expected


def test_remove_friend_rules(client):
    """Participants remove pending/accepted friendships (204); outsiders get 403."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A

    with patch("app.friends.repo.get_friendship_by_id", new_callable=AsyncMock, return_value=None):
        assert client.delete("/api/friends/9", headers=AUTH_HEADER_A).status_code == 404

    outsider_row = _fake_friendship(id=9, requester_id=20, addressee_id=30, status="accepted")
    with patch(
        "app.friends.repo.get_friendship_by_id", new_callable=AsyncMock, return_value=outsider_row
    ):
        assert client.delete("/api/friends/9", headers=AUTH_HEADER_A).status_code == 403

    declined_row = _fake_friendship(id=9, requester_id=10, addressee_id=20, status="declined")
    with patch(
        "app.friends.repo.get_friendship_by_id", new_callable=AsyncMock, return_value=declined_row
    ):
        assert client.delete("/api/friends/9", headers=AUTH_HEADER_A).status_code == 404

    accepted = _fake_friendship(id=9, requester_id=20, addressee_id=10, status="accepted")
    with (
        patch(
            "app.friends.repo.get_friendship_by_id", new_callable=AsyncMock, return_value=accepted
        ),
        patch("app.friends.repo.delete_friendship", new_callable=AsyncMock) as m_del,
    ):
        resp = client.delete("/api/friends/9", headers=AUTH_HEADER_A)
    assert resp.status_code == 204
    m_del.assert_awaited_once()


# ── Single-Query Friends List & Public Profile Unit Tests ─────────────────────


def test_list_friends_returns_avatar_url_and_online_status(client):
    """GET /api/friends uses Storage.avatar_url and batch online_user_ids cleanly."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    rows = [
        (20, "Bob", "Builder", "Chef", "avatars/20/custom.png"),
        (30, "Charlie", "Chaplin", "Actor", None),
    ]

    with (
        patch("app.friends.repo.list_accepted_friends", new_callable=AsyncMock, return_value=rows),
        patch("app.realtime.repo.count_live_sockets_many", new_callable=AsyncMock) as m_counts,
    ):
        m_counts.return_value = {20: 2, 30: 0}
        resp = client.get("/api/friends", headers=AUTH_HEADER_A)

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert items[0] == {
        "user_id": 20,
        "first_name": "Bob",
        "last_name": "Builder",
        "position": "Chef",
        "avatar_object_key": "avatars/20/custom.png",
        "avatar_url": client.app.state.storage.public_url("avatars/20/custom.png"),
        "is_online": True,
    }
    assert items[1]["avatar_object_key"] is None
    assert items[1]["avatar_url"] == client.app.state.settings.default_avatar_url
    assert items[1]["is_online"] is False

    # Redis outage degrades is_online to False cleanly
    with (
        patch("app.friends.repo.list_accepted_friends", new_callable=AsyncMock, return_value=rows),
        patch(
            "app.realtime.repo.count_live_sockets_many",
            new_callable=AsyncMock,
            side_effect=RedisError("redis down"),
        ),
    ):
        resp_down = client.get("/api/friends", headers=AUTH_HEADER_A)
    assert resp_down.status_code == 200
    assert all(item["is_online"] is False for item in resp_down.json())


def test_public_profile_friendship_statuses_and_privacy(client):
    """GET /users/{id}/profile returns avatar_url, presence, and friendship_status safely."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A

    # Not found / deleted -> 404
    with patch("app.friends.repo.get_active_user", new_callable=AsyncMock, return_value=None):
        assert client.get("/api/users/999/profile", headers=AUTH_HEADER_A).status_code == 404

    bob = _fake_user(20, avatar_object_key="avatars/20/pic.webp")
    cases = [
        (None, None),
        (_fake_friendship(requester_id=10, addressee_id=20, status="pending"), "pending_sent"),
        (_fake_friendship(requester_id=20, addressee_id=10, status="pending"), "pending_received"),
        (_fake_friendship(requester_id=20, addressee_id=10, status="accepted"), "accepted"),
    ]
    for rel, expected_status in cases:
        with (
            patch("app.friends.repo.get_active_user", new_callable=AsyncMock, return_value=bob),
            patch(
                "app.friends.repo.get_live_friendship_for_pair",
                new_callable=AsyncMock,
                return_value=rel,
            ),
            patch("app.realtime.repo.count_live_sockets", new_callable=AsyncMock, return_value=1),
        ):
            resp = client.get("/api/users/20/profile", headers=AUTH_HEADER_A)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 20
        assert data["friendship_status"] == expected_status
        assert data["is_online"] is True
        assert data["avatar_url"] == client.app.state.storage.public_url("avatars/20/pic.webp")
        assert "email" not in data
        assert "birth_date" not in data
        assert "status" not in data

    # Own profile returns friendship_status=None and survives Redis outage cleanly
    alice = _fake_user(10, avatar_object_key=None)
    with (
        patch("app.friends.repo.get_active_user", new_callable=AsyncMock, return_value=alice),
        patch(
            "app.realtime.repo.count_live_sockets",
            new_callable=AsyncMock,
            side_effect=RedisError("down"),
        ),
    ):
        own_resp = client.get("/api/users/10/profile", headers=AUTH_HEADER_A)
    assert own_resp.status_code == 200
    assert own_resp.json()["friendship_status"] is None
    assert own_resp.json()["is_online"] is False
    assert own_resp.json()["avatar_url"] == client.app.state.settings.default_avatar_url


def test_openapi_contains_friends_routes(client):
    """OpenAPI schema exposes all 7 BE-22 endpoints under the friends tag."""
    spec = client.get("/api/openapi.json").json()
    paths = spec["paths"]
    for expected_path in (
        "/api/friends/requests",
        "/api/friends/requests/{friendship_id}/accept",
        "/api/friends/requests/{friendship_id}/decline",
        "/api/friends/{friendship_id}",
        "/api/friends",
        "/api/users/{user_id}/profile",
    ):
        assert expected_path in paths


# ── Real PostgreSQL + Redis Integration & Concurrency Tests ───────────────────


def _seed_db_user(
    email: str,
    *,
    first_name: str = "User",
    last_name: str = "Test",
    position: str = "Developer",
    bio: str = "Hello",
    avatar_object_key: str | None = None,
    status: str = "active",
) -> tuple[int, str]:
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified, first_name, last_name,"
        " position, bio, avatar_object_key, status, token_version)"
        " VALUES (:email, 'hash', TRUE, :first_name, :last_name, :position, :bio,"
        " :avatar_object_key, :status, 1)",
        email=email,
        first_name=first_name,
        last_name=last_name,
        position=position,
        bio=bio,
        avatar_object_key=avatar_object_key,
        status=status,
    )
    uid = sql("SELECT id FROM users WHERE email = :email", email=email)[0][0]
    token, _ = security.create_token(
        AUTH_SECRET, user_id=uid, scope="access", lifetime=timedelta(minutes=15), ver=1
    )
    return uid, token


@contextmanager
def _ws_redis():
    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    for key in client.scan_iter("ws:*"):
        client.delete(key)
    try:
        yield client
    finally:
        for key in client.scan_iter("ws:*"):
            client.delete(key)
        client.close()


def _wait_ws_listener(redis_client: redis.Redis, user_id: int) -> None:
    deadline = time.monotonic() + 5.0
    while redis_client.pubsub_numsub(f"ws:user:{user_id}")[0][1] < 1:
        assert time.monotonic() < deadline
        time.sleep(0.01)


@needs_database
def test_friends_real_database_lifecycle_and_single_query():
    """Full friendship lifecycle on real PostgreSQL plus explicit 1-query check on GET /friends."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, friendships RESTART IDENTITY CASCADE")

    alice_id, alice_tok = _seed_db_user("f_alice@example.com", first_name="Alice", last_name="A")
    bob_id, bob_tok = _seed_db_user("f_bob@example.com", first_name="Bob", last_name="B")
    charlie_id, charlie_tok = _seed_db_user(
        "f_charlie@example.com",
        first_name="Charlie",
        last_name="C",
        avatar_object_key="avatars/3/pic.png",
    )
    deleted_id, _ = _seed_db_user("f_deleted@example.com", first_name="Deleted", status="deleted")

    alice_h = {"Authorization": f"Bearer {alice_tok}"}
    bob_h = {"Authorization": f"Bearer {bob_tok}"}
    charlie_h = {"Authorization": f"Bearer {charlie_tok}"}

    app = build_app(database_url=TEST_DATABASE_URL, jwt_secret=AUTH_SECRET)
    with TestClient(app) as tc:
        # 1. Self & deleted target
        assert (
            tc.post(
                "/api/friends/requests", json={"addressee_id": alice_id}, headers=alice_h
            ).status_code
            == 400
        )
        assert (
            tc.post(
                "/api/friends/requests", json={"addressee_id": deleted_id}, headers=alice_h
            ).status_code
            == 404
        )
        assert tc.get(f"/api/users/{deleted_id}/profile", headers=alice_h).status_code == 404

        # 2. Send request A -> B, reverse B -> A blocked (409), check pending views
        r1 = tc.post("/api/friends/requests", json={"addressee_id": bob_id}, headers=alice_h)
        assert r1.status_code == 201
        req1_id = r1.json()["id"]
        assert (
            tc.post(
                "/api/friends/requests", json={"addressee_id": alice_id}, headers=bob_h
            ).status_code
            == 409
        )

        assert (
            tc.get(f"/api/users/{bob_id}/profile", headers=alice_h).json()["friendship_status"]
            == "pending_sent"
        )
        assert (
            tc.get(f"/api/users/{alice_id}/profile", headers=bob_h).json()["friendship_status"]
            == "pending_received"
        )
        assert (
            tc.get(f"/api/users/{bob_id}/profile", headers=charlie_h).json()["friendship_status"]
            is None
        )

        # 3. Incoming lists & non-addressee protections
        assert tc.get("/api/friends/requests", headers=alice_h).json() == []
        assert [r["id"] for r in tc.get("/api/friends/requests", headers=bob_h).json()] == [req1_id]
        assert (
            tc.post(f"/api/friends/requests/{req1_id}/accept", headers=alice_h).status_code == 403
        )
        assert (
            tc.post(f"/api/friends/requests/{req1_id}/decline", headers=charlie_h).status_code
            == 403
        )

        # 4. Decline clears live constraint so pair can re-request later
        assert (
            tc.post(f"/api/friends/requests/{req1_id}/decline", headers=bob_h).json()["status"]
            == "declined"
        )
        assert tc.post(f"/api/friends/requests/{req1_id}/accept", headers=bob_h).status_code == 409
        assert (
            tc.get(f"/api/users/{bob_id}/profile", headers=alice_h).json()["friendship_status"]
            is None
        )

        # 5. Re-request B -> A and accept; also friend Charlie -> A (custom avatar_object_key)
        r2 = tc.post("/api/friends/requests", json={"addressee_id": alice_id}, headers=bob_h)
        assert r2.status_code == 201
        req2_id = r2.json()["id"]
        assert (
            tc.post(f"/api/friends/requests/{req2_id}/accept", headers=alice_h).json()["status"]
            == "accepted"
        )

        r3 = tc.post("/api/friends/requests", json={"addressee_id": alice_id}, headers=charlie_h)
        assert r3.status_code == 201
        assert (
            tc.post(f"/api/friends/requests/{r3.json()['id']}/accept", headers=alice_h).status_code
            == 200
        )

        # 6. Verify GET /api/friends executes only 1 query for friendships+users regardless of count
        executed_sql: list[str] = []

        def _record_sql(_conn, _cursor, statement, _params, _ctx, _many):
            executed_sql.append(statement)

        event.listen(app.state.engine.sync_engine, "before_cursor_execute", _record_sql)
        try:
            friends_resp = tc.get("/api/friends", headers=alice_h)
        finally:
            event.remove(app.state.engine.sync_engine, "before_cursor_execute", _record_sql)

        assert friends_resp.status_code == 200
        friend_items = friends_resp.json()
        assert [f["user_id"] for f in friend_items] == [bob_id, charlie_id]
        assert friend_items[0]["avatar_url"] == app.state.settings.default_avatar_url
        assert friend_items[1]["avatar_url"] == app.state.storage.public_url("avatars/3/pic.png")
        assert len(executed_sql) == 2  # 1 auth query + 1 joined friends query (zero N+1)
        assert sum("friendships" in stmt for stmt in executed_sql) == 1

        # 7. Unfriend removes relation; repeated delete returns 404
        assert tc.delete(f"/api/friends/{req2_id}", headers=bob_h).status_code == 204
        assert tc.delete(f"/api/friends/{req2_id}", headers=bob_h).status_code == 404
        assert [f["user_id"] for f in tc.get("/api/friends", headers=alice_h).json()] == [
            charlie_id
        ]


@needs_database
def test_friends_real_db_concurrent_requests_and_accept_decline_race():
    """Concurrent bidirectional requests create 1 row; accept vs decline resolves with 409."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, friendships RESTART IDENTITY CASCADE")
    alice_id, _ = _seed_db_user("fr_race_alice@example.com")
    bob_id, _ = _seed_db_user("fr_race_bob@example.com")

    async def run():
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:

            async def send_req(req_id: int, addr_id: int):
                async with session_factory() as s:
                    try:
                        return await friends_service.send_request(
                            s, requester_id=req_id, addressee_id=addr_id
                        )
                    except HTTPException as exc:
                        return exc.status_code

            res_send = await asyncio.gather(send_req(alice_id, bob_id), send_req(bob_id, alice_id))
            winner = next(r for r in res_send if isinstance(r, Friendship))
            loser_codes = [r for r in res_send if isinstance(r, int)]
            assert loser_codes == [409]

            # Concurrent accept vs decline on the winning pending row
            async def respond(kind: str):
                async with session_factory() as s:
                    fn = (
                        friends_service.accept_request
                        if kind == "accept"
                        else friends_service.decline_request
                    )
                    try:
                        return await fn(s, friendship_id=winner.id, user_id=winner.addressee_id)
                    except HTTPException as exc:
                        return exc.status_code

            res_reply = await asyncio.gather(respond("accept"), respond("decline"))
            ok_replies = [r for r in res_reply if isinstance(r, Friendship)]
            conflict_codes = [r for r in res_reply if isinstance(r, int)]
            assert len(ok_replies) == 1
            assert conflict_codes == [409]
        finally:
            await engine.dispose()

    asyncio.run(run())
    assert sql("SELECT COUNT(*) FROM friendships")[0][0] == 1


@needs_database
@needs_redis
def test_friends_and_profile_real_redis_presence():
    """GET /api/friends and GET /users/{id}/profile reflect real WS connect/disconnect in Redis."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, friendships RESTART IDENTITY CASCADE")
    alice_id, alice_tok = _seed_db_user("p_alice@example.com", first_name="Alice")
    bob_id, bob_tok = _seed_db_user("p_bob@example.com", first_name="Bob")
    alice_h = {"Authorization": f"Bearer {alice_tok}"}
    bob_h = {"Authorization": f"Bearer {bob_tok}"}

    app = build_app(
        database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL, jwt_secret=AUTH_SECRET
    )
    with (
        _ws_redis() as rdb,
        running_server(app) as address,
        httpx2.Client(base_url=f"http://{address}", timeout=5.0) as http,
    ):
        req_id = http.post(
            "/api/friends/requests", json={"addressee_id": bob_id}, headers=alice_h
        ).json()["id"]
        assert http.post(f"/api/friends/requests/{req_id}/accept", headers=bob_h).status_code == 200

        # Offline initially
        assert http.get("/api/friends", headers=alice_h).json()[0]["is_online"] is False
        assert (
            http.get(f"/api/users/{bob_id}/profile", headers=alice_h).json()["is_online"] is False
        )

        # Connect Bob over real /ws
        ticket = http.post("/api/ws/ticket", headers=bob_h).json()["ticket"]
        with ws_connect(f"ws://{address}/ws?ticket={ticket}", open_timeout=5.0):
            _wait_ws_listener(rdb, bob_id)
            assert http.get("/api/friends", headers=alice_h).json()[0]["is_online"] is True
            assert (
                http.get(f"/api/users/{bob_id}/profile", headers=alice_h).json()["is_online"]
                is True
            )

        # Disconnected -> offline again
        deadline = time.monotonic() + 3.0
        while http.get(f"/api/users/{bob_id}/profile", headers=alice_h).json()["is_online"]:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert http.get("/api/friends", headers=alice_h).json()[0]["is_online"] is False
