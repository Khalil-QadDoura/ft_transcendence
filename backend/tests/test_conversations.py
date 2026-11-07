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

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.auth.deps import CurrentUser, get_current_user
from app.conversations.models import Conversation, ConversationParticipant, Message

AUTH_HEADER_A = {"Authorization": "Bearer 10"}
AUTH_HEADER_B = {"Authorization": "Bearer 20"}
AUTH_HEADER_OUTSIDER = {"Authorization": "Bearer 99"}

USER_A = CurrentUser(id=10, email="alice@example.com")
USER_B = CurrentUser(id=20, email="bob@example.com")
USER_OUTSIDER = CurrentUser(id=99, email="outsider@example.com")


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
    p.joined_at = datetime.now(UTC)
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
        assert resp.json() == {
            "error": {"code": "401", "detail": "Missing or invalid authentication header"}
        }


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
