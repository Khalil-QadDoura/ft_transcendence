"""Tests for conversations domain and BE-23 requirements.

Covers:
- Direct conversation get-or-create, AI conversations, validation.
- Listing user conversations with unread counts and pagination limit.
- Total unread messages count endpoint (/api/conversations/unread).
- Single conversation retrieval with participant isolation (404 for outsiders).
- Leaving conversations and participant access controls.
- Participant listing, admin-only participant adding, and removal rules.
- Messages send, idempotency key deduplication, pagination, and read receipts.
- 15-minute edit window enforcement and soft deletion.
- Standard 401 unauthorized responses across all endpoints.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import security
from app.auth.deps import get_current_user
from app.conversations import repo as conversations_repo
from app.conversations import service as conversations_service
from app.conversations.models import Conversation, ConversationParticipant, Message
from app.users.models import User

AUTH_SECRET = "test-only-jwt-secret-0123456789abcdef"
USER_A = User(id=10, email="alice@example.com", status="active", token_version=1)
USER_B = User(id=20, email="bob@example.com", status="active", token_version=1)
USER_OUTSIDER = User(id=99, email="outsider@example.com", status="active", token_version=1)

TOKEN_A, _ = security.create_token(
    AUTH_SECRET, user_id=10, scope="access", lifetime=timedelta(minutes=15), ver=1
)
TOKEN_B, _ = security.create_token(
    AUTH_SECRET, user_id=20, scope="access", lifetime=timedelta(minutes=15), ver=1
)
TOKEN_OUTSIDER, _ = security.create_token(
    AUTH_SECRET, user_id=99, scope="access", lifetime=timedelta(minutes=15), ver=1
)

AUTH_HEADER_A = {"Authorization": f"Bearer {TOKEN_A}"}
AUTH_HEADER_B = {"Authorization": f"Bearer {TOKEN_B}"}
AUTH_HEADER_OUTSIDER = {"Authorization": f"Bearer {TOKEN_OUTSIDER}"}


def _fake_conv(
    id: int = 1,
    conv_type: str = "direct",
    title: str | None = None,
    job_id: int | None = None,
    last_message_id: int | None = None,
) -> Conversation:
    now = datetime.now(UTC)
    c = Conversation(
        id=id,
        type=conv_type,
        title=title,
        job_id=job_id,
        last_message_id=last_message_id,
    )
    c.created_at = now
    c.updated_at = now
    return c


def _fake_participant(
    conv_id: int = 1,
    user_id: int = 10,
    role: str = "member",
    last_read_message_id: int | None = None,
) -> ConversationParticipant:
    p = ConversationParticipant(
        id=1,
        conversation_id=conv_id,
        user_id=user_id,
        role=role,
        last_read_message_id=last_read_message_id,
        is_muted=False,
    )
    p.created_at = datetime.now(UTC)
    p.updated_at = datetime.now(UTC)
    p.left_at = None
    return p


def _fake_message(
    id: int = 1,
    conv_id: int = 1,
    author_id: int = 10,
    content: str = "Hello",
    status: str = "sent",
    message_type: str = "text",
    created_at: datetime | None = None,
) -> Message:
    m = Message(
        id=id,
        conversation_id=conv_id,
        author_id=author_id,
        content=content,
        status=status,
        message_type=message_type,
    )
    m.created_at = created_at or datetime.now(UTC)
    m.edited_at = None
    m.deleted_at = None
    return m


# ── Auth & Validation Tests ───────────────────────────────────────────────────


def test_unauthenticated_requests_return_401(client):
    """Every conversation endpoint requires authentication."""
    endpoints = [
        ("GET", "/api/conversations"),
        ("POST", "/api/conversations"),
        ("GET", "/api/conversations/unread"),
        ("GET", "/api/conversations/1"),
        ("DELETE", "/api/conversations/1/leave"),
        ("GET", "/api/conversations/1/participants"),
        ("POST", "/api/conversations/1/participants"),
        ("DELETE", "/api/conversations/1/participants/20"),
        ("GET", "/api/conversations/1/messages"),
        ("POST", "/api/conversations/1/messages"),
        ("PATCH", "/api/conversations/1/messages/1"),
        ("DELETE", "/api/conversations/1/messages/1"),
        ("POST", "/api/conversations/1/read"),
    ]
    for method, path in endpoints:
        resp = getattr(client, method.lower())(path)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"
        assert resp.json()["error"]["detail"] == "Not authenticated"


def test_invalid_tokens_return_401(client):
    """Numeric bearer bypass or invalid tokens return 401."""
    resp = client.get("/api/conversations", headers={"Authorization": "Bearer 42"})
    assert resp.status_code == 401
    assert resp.json()["error"]["detail"] == "Invalid or expired token"

    expired_token, _ = security.create_token(
        AUTH_SECRET, user_id=10, scope="access", lifetime=timedelta(seconds=-10), ver=1
    )
    resp = client.get("/api/conversations", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["detail"] == "Invalid or expired token"


def test_create_direct_requires_peer_user_id(client):
    """Direct conversation creation fails if peer_user_id is missing."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    resp = client.post(
        "/api/conversations",
        json={"type": "direct"},
        headers=AUTH_HEADER_A,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["detail"] == "peer_user_id is required for direct conversations"


def test_create_direct_with_self_forbidden(client):
    """Cannot start a direct conversation with oneself."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    resp = client.post(
        "/api/conversations",
        json={"type": "direct", "peer_user_id": USER_A.id},
        headers=AUTH_HEADER_A,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["detail"] == "Cannot start a conversation with yourself"


# ── Creation & Get Tests ───────────────────────────────────────────────────────


def test_create_direct_conversation_success(client):
    """Creates a new direct conversation between two users."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    fake_c = _fake_conv(id=5, conv_type="direct")

    with (
        patch("app.conversations.service.get_or_create_direct", new_callable=AsyncMock) as m_srv,
        patch("app.conversations.repo.get_conversation_for_user", new_callable=AsyncMock) as m_repo,
    ):
        m_srv.return_value = fake_c
        m_repo.return_value = {
            "id": 5,
            "type": "direct",
            "title": None,
            "job_id": None,
            "job_title": None,
            "last_message_id": None,
            "last_message_content": None,
            "last_message_author_id": None,
            "unread_count": 0,
            "updated_at": fake_c.updated_at,
        }

        resp = client.post(
            "/api/conversations",
            json={"type": "direct", "peer_user_id": 20},
            headers=AUTH_HEADER_A,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == 5
    assert data["type"] == "direct"
    assert data["unread_count"] == 0


def test_get_or_create_direct_rechecks_after_pair_lock():
    """When initial lookup misses, service acquires pair lock and re-checks before insert."""
    existing_conv = _fake_conv(id=77)
    mock_session = AsyncMock()

    with (
        patch(
            "app.conversations.repo.find_direct_conversation",
            new_callable=AsyncMock,
            return_value=None,
        ) as m_find,
        patch(
            "app.conversations.repo.lock_direct_pair",
            new_callable=AsyncMock,
        ) as m_lock,
        patch(
            "app.conversations.repo._query_direct_conversation",
            new_callable=AsyncMock,
            return_value=existing_conv,
        ) as m_recheck,
        patch(
            "app.conversations.repo.create_conversation",
            new_callable=AsyncMock,
        ) as m_create,
    ):
        conv = asyncio.run(
            conversations_service.get_or_create_direct(mock_session, me_id=20, peer_id=10)
        )

    assert conv.id == 77
    m_find.assert_awaited_once_with(mock_session, 20, 10)
    m_lock.assert_awaited_once_with(mock_session, 20, 10)
    m_recheck.assert_awaited_once_with(mock_session, 20, 10)
    m_create.assert_not_awaited()


def test_lock_direct_pair_uses_canonical_unordered_key():
    """lock_direct_pair locks the same advisory key regardless of (me_id, peer_id) order."""
    session = AsyncMock()
    asyncio.run(conversations_repo.lock_direct_pair(session, 10, 20))
    asyncio.run(conversations_repo.lock_direct_pair(session, 20, 10))
    assert session.execute.await_count == 2
    assert session.execute.await_args_list[0].args[1] == {"pair_key": "direct:10:20"}
    assert session.execute.await_args_list[1].args[1] == {"pair_key": "direct:10:20"}


def test_create_ai_conversation(client):
    """Creates an AI conversation for the user."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    fake_c = _fake_conv(id=9, conv_type="ai")

    with (
        patch("app.conversations.service.create_ai_conversation", new_callable=AsyncMock) as m_srv,
        patch("app.conversations.repo.get_conversation_for_user", new_callable=AsyncMock) as m_repo,
    ):
        m_srv.return_value = fake_c
        m_repo.return_value = None

        resp = client.post(
            "/api/conversations",
            json={"type": "ai"},
            headers=AUTH_HEADER_A,
        )

    assert resp.status_code == 201
    assert resp.json()["id"] == 9
    assert resp.json()["type"] == "ai"


def test_list_conversations(client):
    """Lists conversations for user with limit and unread counts."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    now = datetime.now(UTC)

    mock_rows = [
        {
            "id": 1,
            "type": "direct",
            "title": None,
            "job_id": 101,
            "job_title": "Senior Python Engineer",
            "last_message_id": 42,
            "last_message_content": "See you tomorrow!",
            "last_message_author_id": 20,
            "unread_count": 3,
            "updated_at": now,
        }
    ]

    with patch(
        "app.conversations.repo.list_conversations_for_user", new_callable=AsyncMock
    ) as m_list:
        m_list.return_value = mock_rows
        resp = client.get("/api/conversations?limit=25", headers=AUTH_HEADER_A)

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == 1
    assert items[0]["job_title"] == "Senior Python Engineer"
    assert items[0]["unread_count"] == 3


def test_get_unread_total(client):
    """Returns total unread count for current user."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A

    with patch("app.conversations.repo.get_total_unread", new_callable=AsyncMock) as m_unread:
        m_unread.return_value = 7
        resp = client.get("/api/conversations/unread", headers=AUTH_HEADER_A)

    assert resp.status_code == 200
    assert resp.json() == {"total_unread": 7}


def test_get_conversation_by_id_success(client):
    """Participant gets conversation details."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    now = datetime.now(UTC)

    with patch("app.conversations.repo.get_conversation_for_user", new_callable=AsyncMock) as m_get:
        m_get.return_value = {
            "id": 1,
            "type": "direct",
            "title": "Chat",
            "job_id": None,
            "job_title": None,
            "last_message_id": None,
            "last_message_content": None,
            "last_message_author_id": None,
            "unread_count": 0,
            "updated_at": now,
        }
        resp = client.get("/api/conversations/1", headers=AUTH_HEADER_A)

    assert resp.status_code == 200
    assert resp.json()["id"] == 1


def test_get_conversation_by_id_forbidden_or_not_found(client):
    """Non-participant receives 404 to avoid leaking existence."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_OUTSIDER

    with patch("app.conversations.repo.get_conversation_for_user", new_callable=AsyncMock) as m_get:
        m_get.return_value = None
        resp = client.get("/api/conversations/1", headers=AUTH_HEADER_OUTSIDER)

    assert resp.status_code == 404
    assert resp.json()["error"]["detail"] == "not found or forbidden"


def test_leave_conversation(client):
    """Active participant can leave a conversation."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    p = _fake_participant()

    with (
        patch("app.conversations.repo.get_participant", new_callable=AsyncMock) as m_part,
        patch("app.conversations.repo.remove_participant", new_callable=AsyncMock) as m_rem,
    ):
        m_part.return_value = p
        resp = client.delete("/api/conversations/1/leave", headers=AUTH_HEADER_A)

    assert resp.status_code == 204
    m_rem.assert_awaited_once()


# ── Participant Management Tests ──────────────────────────────────────────────


def test_list_participants(client):
    """List active participants of a conversation."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    p1 = _fake_participant(user_id=10, role="admin")
    p2 = _fake_participant(user_id=20, role="member")

    with (
        patch("app.conversations.repo.get_participant", new_callable=AsyncMock) as m_check,
        patch("app.conversations.repo.list_participants", new_callable=AsyncMock) as m_list,
    ):
        m_check.return_value = p1
        m_list.return_value = [p1, p2]
        resp = client.get("/api/conversations/1/participants", headers=AUTH_HEADER_A)

    assert resp.status_code == 200
    parts = resp.json()
    assert len(parts) == 2
    assert parts[0]["user_id"] == 10
    assert parts[0]["role"] == "admin"
    assert parts[1]["user_id"] == 20


def test_add_participant_admin_only(client):
    """Only admins can add new participants to a conversation."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    member_p = _fake_participant(user_id=10, role="member")
    admin_p = _fake_participant(user_id=10, role="admin")

    with patch("app.conversations.repo.get_participant", new_callable=AsyncMock) as m_check:
        # Non-admin attempt
        m_check.return_value = member_p
        resp = client.post(
            "/api/conversations/1/participants",
            json={"user_id": 30, "role": "member"},
            headers=AUTH_HEADER_A,
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["detail"] == "only admins can add participants"

        # Admin attempt
        m_check.return_value = admin_p
        with patch("app.conversations.repo.add_participant", new_callable=AsyncMock):
            resp2 = client.post(
                "/api/conversations/1/participants",
                json={"user_id": 30, "role": "member"},
                headers=AUTH_HEADER_A,
            )
            assert resp2.status_code == 201
            assert resp2.json() == {"added": True}


def test_remove_participant_rules(client):
    """Admin can remove others; members can only remove themselves."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    member_p = _fake_participant(user_id=10, role="member")
    admin_p = _fake_participant(user_id=10, role="admin")

    with patch("app.conversations.repo.get_participant", new_callable=AsyncMock) as m_check:
        # Member trying to remove another user -> 403
        m_check.return_value = member_p
        resp = client.delete("/api/conversations/1/participants/20", headers=AUTH_HEADER_A)
        assert resp.status_code == 403

        # Member removing themselves -> 204
        with patch("app.conversations.repo.remove_participant", new_callable=AsyncMock):
            resp_self = client.delete("/api/conversations/1/participants/10", headers=AUTH_HEADER_A)
            assert resp_self.status_code == 204

        # Admin removing another user -> 204
        m_check.return_value = admin_p
        with patch("app.conversations.repo.remove_participant", new_callable=AsyncMock):
            resp_admin = client.delete(
                "/api/conversations/1/participants/20", headers=AUTH_HEADER_A
            )
            assert resp_admin.status_code == 204


# ── Messages & Realtime Tests ─────────────────────────────────────────────────


def test_send_message_and_broadcast(client):
    """Sends message, updates state, and broadcasts payload."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    fake_c = _fake_conv(id=1)
    fake_m = _fake_message(id=100, conv_id=1, author_id=10, content="Hello Bob!")

    with (
        patch("app.conversations.service.send_message", new_callable=AsyncMock) as m_send,
        patch(
            "app.conversations.repo.get_active_participant_ids", new_callable=AsyncMock
        ) as m_parts,
        patch(
            "app.realtime.connection_manager.manager.send_to_user", new_callable=AsyncMock
        ) as m_ws,
    ):
        m_send.return_value = (fake_c, [fake_m])
        m_parts.return_value = [10, 20]

        resp = client.post(
            "/api/conversations/1/messages",
            json={"content": "Hello Bob!", "idempotency_key": "idem-123"},
            headers=AUTH_HEADER_A,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["content"] == "Hello Bob!"
    assert m_ws.await_count == 2


def test_edit_message_within_window(client):
    """Author can edit message within 15 minutes."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    p = _fake_participant(user_id=10)
    fake_m = _fake_message(id=10, conv_id=1, author_id=10, content="Original")
    edited_m = _fake_message(id=10, conv_id=1, author_id=10, content="Edited")

    with (
        patch("app.conversations.repo.get_participant", new_callable=AsyncMock) as m_part,
        patch("app.conversations.repo.get_message", new_callable=AsyncMock) as m_msg,
        patch("app.conversations.repo.edit_message", new_callable=AsyncMock) as m_edit,
        patch("app.conversations.repo.get_active_participant_ids", new_callable=AsyncMock) as m_ids,
        patch("app.realtime.connection_manager.manager.send_to_user", new_callable=AsyncMock),
    ):
        m_part.return_value = p
        m_msg.return_value = fake_m
        m_edit.return_value = edited_m
        m_ids.return_value = [10, 20]

        resp = client.patch(
            "/api/conversations/1/messages/10",
            json={"content": "Edited"},
            headers=AUTH_HEADER_A,
        )

    assert resp.status_code == 200
    assert resp.json()["content"] == "Edited"


def test_edit_message_after_window_expired(client):
    """Editing after 15 minutes fails with 409 conflict."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    p = _fake_participant(user_id=10)
    old_time = datetime.now(UTC) - timedelta(minutes=20)
    fake_m = _fake_message(id=10, conv_id=1, author_id=10, content="Old", created_at=old_time)

    with (
        patch("app.conversations.repo.get_participant", new_callable=AsyncMock) as m_part,
        patch("app.conversations.repo.get_message", new_callable=AsyncMock) as m_msg,
    ):
        m_part.return_value = p
        m_msg.return_value = fake_m

        resp = client.patch(
            "/api/conversations/1/messages/10",
            json={"content": "Too late"},
            headers=AUTH_HEADER_A,
        )

    assert resp.status_code == 409
    assert resp.json()["error"]["detail"] == "edit window expired (15 minutes)"


def test_edit_another_users_message_forbidden(client):
    """User cannot edit another person's message."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    p = _fake_participant(user_id=10)
    bobs_msg = _fake_message(id=10, conv_id=1, author_id=20, content="Bob's msg")

    with (
        patch("app.conversations.repo.get_participant", new_callable=AsyncMock) as m_part,
        patch("app.conversations.repo.get_message", new_callable=AsyncMock) as m_msg,
    ):
        m_part.return_value = p
        m_msg.return_value = bobs_msg

        resp = client.patch(
            "/api/conversations/1/messages/10",
            json={"content": "Hacked"},
            headers=AUTH_HEADER_A,
        )

    assert resp.status_code == 403
    assert resp.json()["error"]["detail"] == "cannot edit another user's message"


def test_soft_delete_message(client):
    """Author can soft delete their own message."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_A
    p = _fake_participant(user_id=10)
    fake_m = _fake_message(id=10, conv_id=1, author_id=10, content="To be deleted")

    with (
        patch("app.conversations.repo.get_participant", new_callable=AsyncMock) as m_part,
        patch("app.conversations.repo.get_message", new_callable=AsyncMock) as m_msg,
        patch("app.conversations.repo.soft_delete_message", new_callable=AsyncMock) as m_del,
        patch("app.conversations.repo.get_active_participant_ids", new_callable=AsyncMock) as m_ids,
        patch("app.realtime.connection_manager.manager.send_to_user", new_callable=AsyncMock),
    ):
        m_part.return_value = p
        m_msg.return_value = fake_m
        m_ids.return_value = [10, 20]

        resp = client.delete("/api/conversations/1/messages/10", headers=AUTH_HEADER_A)

    assert resp.status_code == 204
    m_del.assert_awaited_once()


def test_mark_read_advances_pointer_and_notifies(client):
    """Marking read updates pointers and emits conversation_updated."""
    client.app.dependency_overrides[get_current_user] = lambda: USER_B

    with (
        patch("app.conversations.service.mark_read", new_callable=AsyncMock) as m_read,
        patch(
            "app.conversations.repo.get_active_participant_ids", new_callable=AsyncMock
        ) as m_parts,
        patch("app.conversations.repo.get_total_unread", new_callable=AsyncMock) as m_unread,
        patch(
            "app.realtime.connection_manager.manager.send_to_user", new_callable=AsyncMock
        ) as m_ws,
    ):
        m_parts.return_value = [10, 20]
        m_unread.return_value = 0

        resp = client.post(
            "/api/conversations/1/read",
            json={"last_message_id": 100},
            headers=AUTH_HEADER_B,
        )

    assert resp.status_code == 204
    assert m_read.await_count == 1
    call_args = m_read.await_args[0]
    assert call_args[1:] == (1, USER_B.id, 100)
    assert m_ws.await_count == 2


def test_openapi_contains_conversations_routes(client):
    """The OpenAPI document documents /api/conversations endpoints."""
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/conversations" in paths
    assert "/api/conversations/unread" in paths
    assert "/api/conversations/{conv_id}" in paths
    assert "/api/conversations/{conv_id}/leave" in paths
    assert "/api/conversations/{conv_id}/participants" in paths
    assert "/api/conversations/{conv_id}/messages" in paths
    assert "/api/conversations/{conv_id}/read" in paths


# ── Real Database Tests (Requires live PostgreSQL with PostGIS) ────────────────


PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)


def _seed_db_user(email: str, is_active: bool = True, token_version: int = 1) -> None:
    status_str = "active" if is_active else "deleted"
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified, status, token_version,"
        " first_name, last_name, position, birth_date, bio)"
        " VALUES (:email, :password_hash, true, :status, :token_version,"
        " 'Test', 'User', 'Dev', '1995-01-01', 'Bio')",
        email=email,
        password_hash=PASSWORD_HASH,
        status=status_str,
        token_version=token_version,
    )


@needs_database
def test_conversations_real_database_lifecycle():
    """Real PostgreSQL integration: conversations lifecycle, auth, idempotency, read receipts."""
    alembic("upgrade", "head")
    sql(
        "TRUNCATE users, companies, jobs, conversations, conversation_participants, messages "
        "RESTART IDENTITY CASCADE"
    )

    with TestClient(build_app(database_url=TEST_DATABASE_URL)) as test_client:
        # 1. Seed users in real PostgreSQL
        _seed_db_user("alice@example.com")
        _seed_db_user("bob@example.com")
        _seed_db_user("charlie@example.com")

        # 2. Login to get real signed JWT tokens
        r_a = test_client.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": PASSWORD},
        )
        assert r_a.status_code == 200
        alice_h = {"Authorization": f"Bearer {r_a.json()['access_token']}"}
        alice_id = test_client.get("/api/users/me", headers=alice_h).json()["id"]

        r_b = test_client.post(
            "/api/auth/login",
            json={"email": "bob@example.com", "password": PASSWORD},
        )
        assert r_b.status_code == 200
        bob_h = {"Authorization": f"Bearer {r_b.json()['access_token']}"}
        bob_id = test_client.get("/api/users/me", headers=bob_h).json()["id"]

        r_c = test_client.post(
            "/api/auth/login",
            json={"email": "charlie@example.com", "password": PASSWORD},
        )
        assert r_c.status_code == 200
        charlie_h = {"Authorization": f"Bearer {r_c.json()['access_token']}"}

        # 3. Create company and jobs for Alice
        r_comp = test_client.post(
            "/api/companies",
            json={"name": "Alice Tech", "country": "UAE", "city": "Abu Dhabi"},
            headers=alice_h,
        )
        assert r_comp.status_code == 201
        company_id = r_comp.json()["id"]

        # Insert an open job for Alice's company directly in DB
        sql(
            "INSERT INTO jobs (owner_id, title, description, status, latitude, longitude, location,"
            " schedule, urgency) VALUES (:owner_id, 'Senior Python Engineer', 'Great role',"
            " 'open', 24.4539, 54.3773, 'Abu Dhabi', 'full_time', 'normal')",
            owner_id=company_id,
        )
        job_id = sql(
            "SELECT id FROM jobs WHERE owner_id = :owner_id AND status = 'open' LIMIT 1",
            owner_id=company_id,
        )[0][0]

        # Insert a deleted job for Alice's company
        sql(
            "INSERT INTO jobs (owner_id, title, description, status, latitude, longitude, location,"
            " schedule, urgency) VALUES (:owner_id, 'Archived Role', 'Closed',"
            " 'deleted', 24.4539, 54.3773, 'Abu Dhabi', 'full_time', 'normal')",
            owner_id=company_id,
        )
        del_job_id = sql(
            "SELECT id FROM jobs WHERE owner_id = :owner_id AND status = 'deleted' LIMIT 1",
            owner_id=company_id,
        )[0][0]

        # 4. Job ownership and status validation
        # Bob cannot start conversation using Alice's company job -> 403 Forbidden
        r_forbidden = test_client.post(
            "/api/conversations",
            json={"peer_user_id": alice_id, "job_id": job_id},
            headers=bob_h,
        )
        assert r_forbidden.status_code == 403
        assert (
            r_forbidden.json()["error"]["detail"]
            == "job_id does not belong to your company or is not active"
        )

        # Alice cannot start conversation referencing a deleted job -> 403 Forbidden
        r_del_job = test_client.post(
            "/api/conversations",
            json={"peer_user_id": bob_id, "job_id": del_job_id},
            headers=alice_h,
        )
        assert r_del_job.status_code == 403

        # 5. Alice creates direct conversation with Bob referencing her open job -> 201 Created
        r_conv = test_client.post(
            "/api/conversations",
            json={"peer_user_id": bob_id, "job_id": job_id},
            headers=alice_h,
        )
        assert r_conv.status_code == 201
        conv_id = r_conv.json()["id"]
        assert r_conv.json()["type"] == "direct"
        assert r_conv.json()["job_id"] == job_id
        assert r_conv.json()["job_title"] == "Senior Python Engineer"

        # 6. Idempotency of get-or-create direct:
        # Bob calls create conversation with Alice -> 201 (returns existing conversation)
        r_conv_exist = test_client.post(
            "/api/conversations",
            json={"peer_user_id": alice_id},
            headers=bob_h,
        )
        assert r_conv_exist.status_code == 201
        assert r_conv_exist.json()["id"] == conv_id

        # 7. List participants
        r_parts = test_client.get(f"/api/conversations/{conv_id}/participants", headers=alice_h)
        assert r_parts.status_code == 200
        parts = r_parts.json()
        assert len(parts) == 2
        p_ids = {p["user_id"] for p in parts}
        assert p_ids == {alice_id, bob_id}
        # Check joined_at is populated via alias created_at
        assert "joined_at" in parts[0]
        assert parts[0]["joined_at"] is not None

        # 8. Outsider isolation: Charlie cannot view conversation or send messages
        r_outsider_get = test_client.get(f"/api/conversations/{conv_id}", headers=charlie_h)
        assert r_outsider_get.status_code == 404

        r_outsider_send = test_client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"content": "I am eavesdropping"},
            headers=charlie_h,
        )
        assert r_outsider_send.status_code == 403

        # 9. Send message with idempotency key
        r_msg = test_client.post(
            f"/api/conversations/{conv_id}/messages",
            json={
                "content": "Hi Bob, interested in the role?",
                "idempotency_key": "msg-key-1",
            },
            headers=alice_h,
        )
        assert r_msg.status_code == 200
        items = r_msg.json()["items"]
        assert len(items) == 1
        msg_id = items[0]["id"]
        assert items[0]["content"] == "Hi Bob, interested in the role?"

        # Duplicate send with same idempotency key returns same message without duplicating
        r_msg_dup = test_client.post(
            f"/api/conversations/{conv_id}/messages",
            json={
                "content": "Hi Bob, interested in the role?",
                "idempotency_key": "msg-key-1",
            },
            headers=alice_h,
        )
        assert r_msg_dup.status_code == 200
        assert r_msg_dup.json()["items"][0]["id"] == msg_id

        # 10. Unread counts
        # Alice sent the message, so Alice unread count should be 0
        r_unread_a = test_client.get("/api/conversations/unread", headers=alice_h)
        assert r_unread_a.status_code == 200
        assert r_unread_a.json()["total_unread"] == 0

        # Bob has not read Alice's message, so Bob unread count should be 1
        r_unread_b = test_client.get("/api/conversations/unread", headers=bob_h)
        assert r_unread_b.status_code == 200
        assert r_unread_b.json()["total_unread"] == 1

        # Check Bob's conversation detail
        r_conv_b = test_client.get(f"/api/conversations/{conv_id}", headers=bob_h)
        assert r_conv_b.status_code == 200
        assert r_conv_b.json()["unread_count"] == 1

        # 11. Bob marks message as read
        r_read = test_client.post(
            f"/api/conversations/{conv_id}/read",
            json={"last_message_id": msg_id},
            headers=bob_h,
        )
        assert r_read.status_code == 204

        # Bob's unread count should now be 0
        r_unread_b_after = test_client.get("/api/conversations/unread", headers=bob_h)
        assert r_unread_b_after.status_code == 200
        assert r_unread_b_after.json()["total_unread"] == 0


@needs_database
def test_concurrent_get_or_create_direct_is_atomic():
    """Concurrent opposite-order get_or_create_direct calls yield one conversation atomically."""
    alembic("upgrade", "head")
    sql(
        "TRUNCATE users, conversations, conversation_participants, messages "
        "RESTART IDENTITY CASCADE"
    )
    _seed_db_user("race_alice@example.com")
    _seed_db_user("race_bob@example.com")
    alice_id = sql("SELECT id FROM users WHERE email = 'race_alice@example.com'")[0][0]
    bob_id = sql("SELECT id FROM users WHERE email = 'race_bob@example.com'")[0][0]

    async def _exercise() -> tuple[int, int]:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        orig_find = conversations_repo.find_direct_conversation
        seen = 0
        both_missed = asyncio.Event()

        async def barrier_find(session, u1: int, u2: int):
            nonlocal seen
            res = await orig_find(session, u1, u2)
            assert res is None
            seen += 1
            if seen == 2:
                both_missed.set()
            await asyncio.wait_for(both_missed.wait(), timeout=5.0)
            return res

        async def run_one(me_id: int, peer_id: int) -> int:
            async with maker() as session:
                conv = await conversations_service.get_or_create_direct(
                    session, me_id=me_id, peer_id=peer_id
                )
                return conv.id

        try:
            with patch(
                "app.conversations.repo.find_direct_conversation",
                side_effect=barrier_find,
            ):
                id_ab, id_ba = await asyncio.gather(
                    run_one(alice_id, bob_id),
                    run_one(bob_id, alice_id),
                )

            assert id_ab == id_ba

            async with maker() as check_session:
                found = await conversations_repo.find_direct_conversation(
                    check_session, alice_id, bob_id
                )
                assert found is not None
                assert found.id == id_ab

            return id_ab, id_ba
        finally:
            await engine.dispose()

    id_ab, id_ba = asyncio.run(_exercise())
    assert id_ab == id_ba
    direct_count = sql("SELECT COUNT(*) FROM conversations WHERE type = 'direct'")[0][0]
    assert direct_count == 1
