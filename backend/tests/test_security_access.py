"""Cross-user access (BE-13): Ana cannot read or change what belongs to Ben or Cara.

One world, on a real database, a real Redis and a real server: Ben is a job seeker with an intro
video, an application, a friend request and a chat with Cara; Cara is an employer with a company,
an open job and a draft; both are in a game room. Ana is logged in and has her own company and her
own chat with Ben. She tries every route with their ids: in the path, in the query, in the body,
and on both WebSockets. Each try must be refused with 403 or 404 (never 200, never 500), and at
the end nothing of Ben's or Cara's has changed.

The users are made up (added straight to the database). The video, the application and the game
room are added straight to the database too: making them through the API needs a moderated
video and a full game, which other tests cover.
"""

import json
import uuid
from datetime import timedelta

import httpx2
import pytest
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
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from app.auth import security
from app.auth.constants import ACCESS_SCOPE

pytestmark = [needs_database, needs_redis]

WAIT = 5  # seconds to wait for a frame or a close
OPEN_JOB = {
    "title": "Barista",
    "description": "Make the coffee.",
    "latitude": 24.45,
    "longitude": 54.38,
    "location": "Abu Dhabi",
    "status": "open",
}


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


class User:
    def __init__(self, app, email: str):
        [(self.id,)] = sql(
            "INSERT INTO users (email, is_email_verified, first_name, last_name, birth_date)"
            " VALUES (:email, true, 'First', 'Last', '1990-01-01') RETURNING id",
            email=email,
        )
        token, _ = security.create_token(
            app.state.settings.jwt_secret, self.id, ACCESS_SCOPE, timedelta(minutes=15), ver=1
        )
        self.headers = {"Authorization": f"Bearer {token}"}


@pytest.fixture
def world():
    """The app on a running server, the three users, and the ids of Ben's and Cara's things."""
    sql("TRUNCATE users, game_rooms RESTART IDENTITY CASCADE")
    app = build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    ana, ben, cara = (User(app, f"{name}@example.com") for name in ("ana", "ben", "cara"))
    with running_server(app) as server:
        base = f"http://{server}"

        def call(user: User, method: str, path: str, body=None) -> httpx2.Response:
            return httpx2.request(method, base + path, json=body, headers=user.headers)

        def made(user: User, method: str, path: str, body=None) -> dict:
            response = call(user, method, path, body)
            assert response.status_code in (200, 201), response.text
            return response.json()

        ids = {"ana": ana.id, "ben": ben.id, "cara": cara.id}
        ids["company"] = made(cara, "POST", "/api/companies", {"name": "Cafe Cara"})["id"]
        ids["job"] = made(cara, "POST", "/api/jobs", OPEN_JOB)["id"]
        ids["draft"] = made(cara, "POST", "/api/jobs", {**OPEN_JOB, "status": "draft"})["id"]
        ids["chat"] = made(ben, "POST", "/api/conversations", {"peer_user_id": cara.id})["id"]
        sent = made(ben, "POST", f"/api/conversations/{ids['chat']}/messages", {"content": "Hi"})
        ids["message"] = sent["items"][0]["id"]
        ids["request"] = made(ben, "POST", "/api/friends/requests", {"addressee_id": cara.id})["id"]
        # Ana's own things: a company (sent with Cara's id as owner, which must be ignored) and
        # a chat with Ben, with one message from each.
        mine = made(ana, "POST", "/api/companies", {"name": "Ana Co", "owner_user_id": cara.id})
        assert mine["owner_user_id"] == ana.id
        ids["ana_chat"] = made(ana, "POST", "/api/conversations", {"peer_user_id": ben.id})["id"]
        made(ana, "POST", f"/api/conversations/{ids['ana_chat']}/messages", {"content": "Hey"})
        reply = made(
            ben, "POST", f"/api/conversations/{ids['ana_chat']}/messages", {"content": "Yo"}
        )
        ids["ben_reply"] = reply["items"][0]["id"]
        [(ids["video"],)] = sql(
            "INSERT INTO intro_videos (user_id, object_key, duration_sec, size_bytes,"
            " content_type, moderation_status, lifecycle_status)"
            " VALUES (:ben, :key, 20, 1000, 'video/mp4', 'approved', 'posted') RETURNING id",
            ben=ben.id,
            key=f"videos/{ben.id}/{uuid.uuid4()}.mp4",
        )
        [(ids["application"],)] = sql(
            "INSERT INTO applications (job_id, applicant_id, company_id, intro_video_id)"
            " VALUES (:job, :ben, :company, :video) RETURNING id",
            job=ids["job"],
            ben=ben.id,
            company=ids["company"],
            video=ids["video"],
        )
        [(ids["room"],)] = sql(
            "INSERT INTO game_rooms (target_size, state, discussion_started_at)"
            " VALUES (5, 'discussion', now()) RETURNING id"
        )
        for label, user_id in (("Player 1", ben.id), ("Player 2", cara.id), ("Player 3", None)):
            sql(
                "INSERT INTO game_participants (room_id, user_id, display_label)"
                " VALUES (:room, :user_id, :label)",
                room=ids["room"],
                user_id=user_id,
                label=label,
            )
        yield {"server": server, "call": call, "ana": ana, "ben": ben, "cara": cara, "ids": ids}


def their_data(ids: dict) -> list:
    """Everything of Ben's and Cara's that Ana's tries could change, read from the database."""
    return [
        sql("SELECT email, first_name, status, token_version FROM users ORDER BY id"),
        sql("SELECT owner_user_id, name, status FROM companies ORDER BY id"),
        sql("SELECT id, title, status FROM jobs ORDER BY id"),
        sql("SELECT lifecycle_status FROM intro_videos"),
        sql("SELECT status FROM applications"),
        sql("SELECT status FROM friendships"),
        sql(
            "SELECT conversation_id, user_id, left_at IS NULL, last_read_message_id"
            " FROM conversation_participants ORDER BY id"
        ),
        sql("SELECT id, content, status, deleted_at IS NULL FROM messages ORDER BY id"),
        sql("SELECT room_id, user_id FROM game_participants ORDER BY id"),
        sql("SELECT count(*) FROM game_votes"),
        sql("SELECT count(*) FROM game_messages"),
    ]


# (method, path, body, the answer Ana gets). {name} is an id from the world fixture.
ANA_TRIES = [
    # Ben's intro video: through its id in the path, and his upload key in a body.
    ("POST", "/api/media/intro-video/{video}/post", None, 404),
    ("POST", "/api/media/intro-video/{video}/unpost", None, 404),
    ("POST", "/api/media/intro-video/{video}/delete", None, 404),
    (
        "POST",
        "/api/media/intro-video/confirm",
        {
            "object_key": "users/{ben}/intro/00000000-0000-4000-8000-000000000000.mp4",
            "duration_sec": 10,
            "size_bytes": 1000,
            "content_type": "video/mp4",
        },
        400,
    ),
    # Ben's avatar and Cara's logo uploads, by their keys in the body.
    (
        "POST",
        "/api/media/avatar/confirm",
        {"object_key": "staging/avatars/{ben}/00000000-0000-4000-8000-000000000000.png"},
        400,
    ),
    (
        "POST",
        "/api/media/company-logo/confirm",
        {"object_key": "staging/logos/{company}/00000000-0000-4000-8000-000000000000.png"},
        400,
    ),
    # Ben's application to Cara's job.
    ("GET", "/api/applications/{application}", None, 403),
    ("DELETE", "/api/applications/{application}", None, 404),
    ("PATCH", "/api/applications/{application}/status", {"status": "rejected"}, 403),
    ("GET", "/api/jobs/{job}/applications", None, 403),
    ("GET", "/api/jobs/{job}/applications?status=submitted", None, 403),
    # Cara's jobs: the draft is invisible, the open one cannot be changed.
    ("GET", "/api/jobs/{draft}", None, 404),
    ("PATCH", "/api/jobs/{job}", {"title": "Taken over"}, 404),
    ("DELETE", "/api/jobs/{job}", None, 404),
    ("POST", "/api/jobs/{draft}/apply", None, 404),
    # Cara's company: only "my company" routes exist, and they refuse a foreign id.
    (
        "PATCH",
        "/api/companies/me",
        {"name": "X", "country": "AE", "city": "AD", "id": "{company}"},
        422,
    ),
    # Ben and Cara's chat.
    ("GET", "/api/conversations/{chat}", None, 404),
    ("GET", "/api/conversations/{chat}/messages", None, 403),
    ("GET", "/api/conversations/{chat}/participants", None, 403),
    ("POST", "/api/conversations/{chat}/messages", {"content": "Hello"}, 403),
    ("PATCH", "/api/conversations/{chat}/messages/{message}", {"content": "Changed"}, 403),
    ("DELETE", "/api/conversations/{chat}/messages/{message}", None, 403),
    ("POST", "/api/conversations/{chat}/read", {"last_message_id": "{message}"}, 403),
    ("POST", "/api/conversations/{chat}/participants", {"user_id": "{ana}"}, 403),
    ("DELETE", "/api/conversations/{chat}/participants/{ben}", None, 403),
    ("DELETE", "/api/conversations/{chat}/leave", None, 403),
    # Through her own chat with Ben: their message's id, and Ben's reply to her.
    (
        "POST",
        "/api/conversations/{ana_chat}/messages",
        {"content": "Quote", "reply_to_id": "{message}"},
        404,
    ),
    ("PATCH", "/api/conversations/{ana_chat}/messages/{message}", {"content": "x"}, 404),
    ("DELETE", "/api/conversations/{ana_chat}/messages/{message}", None, 404),
    ("PATCH", "/api/conversations/{ana_chat}/messages/{ben_reply}", {"content": "x"}, 403),
    ("DELETE", "/api/conversations/{ana_chat}/messages/{ben_reply}", None, 403),
    ("POST", "/api/conversations/{ana_chat}/participants", {"user_id": "{cara}"}, 403),
    ("DELETE", "/api/conversations/{ana_chat}/participants/{ben}", None, 403),
    # A chat tied to Cara's job, which is not Ana's.
    ("POST", "/api/conversations", {"peer_user_id": "{ben}", "job_id": "{job}"}, 403),
    # Ben's friend request to Cara.
    ("POST", "/api/friends/requests/{request}/accept", None, 403),
    ("POST", "/api/friends/requests/{request}/decline", None, 403),
    ("DELETE", "/api/friends/{request}", None, 403),
    # Ben and Cara's game room: state, chat, start, votes and results.
    ("GET", "/api/game/rooms/{room}", None, 403),
    ("GET", "/api/game/rooms/{room}/messages", None, 403),
    ("POST", "/api/game/rooms/{room}/start", None, 403),
    ("POST", "/api/game/rooms/{room}/votes", {"target_participant_id": 1, "guess": "bot"}, 403),
    ("GET", "/api/game/rooms/{room}/results", None, 403),
]


def fill(value, ids: dict):
    """The value with each {name} replaced by its id (a whole "{name}" becomes the number)."""
    if isinstance(value, dict):
        return {key: fill(item, ids) for key, item in value.items()}
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        return ids[value[1:-1]]
    return value.format(**ids) if isinstance(value, str) else value


def test_ana_cannot_reach_ben_or_caras_things_over_http(world):
    ids, call, ana = world["ids"], world["call"], world["ana"]
    before = their_data(ids)
    for method, path, body, expected in ANA_TRIES:
        response = call(ana, method, fill(path, ids), fill(body, ids))
        assert response.status_code == expected, f"{method} {path}: {response.text}"
        assert response.json()["error"]["code"] == str(expected)
    assert their_data(ids) == before


def test_the_other_side_of_each_relation_is_refused_too(world):
    """Ben, the applicant, cannot move his own application; Cara, the employer, cannot
    withdraw it. Ben cannot change Cara's job."""
    ids, call, ben, cara = world["ids"], world["call"], world["ben"], world["cara"]
    before = their_data(ids)
    path = f"/api/applications/{ids['application']}"
    assert call(ben, "PATCH", f"{path}/status", {"status": "hired"}).status_code == 403
    assert call(cara, "DELETE", path).status_code == 404
    assert call(ben, "PATCH", f"/api/jobs/{ids['job']}", {"title": "Mine"}).status_code == 404
    assert their_data(ids) == before


def test_ana_lists_only_her_own_things(world):
    ids, call, ana = world["ids"], world["call"], world["ana"]
    conversations = call(ana, "GET", "/api/conversations").json()
    assert [chat["id"] for chat in conversations] == [ids["ana_chat"]]
    assert call(ana, "GET", "/api/applications/mine").json()["items"] == []
    assert call(ana, "GET", "/api/friends/requests").json() == []
    assert call(ana, "GET", "/api/friends").json() == []
    assert call(ana, "GET", "/api/media/intro-video/mine").json()["items"] == []
    assert call(ana, "GET", "/api/jobs/mine").json() == []
    assert call(ana, "GET", "/api/game/rooms/active").json() is None
    assert call(ana, "GET", "/api/companies/me").json()["name"] == "Ana Co"


def test_a_public_profile_shows_no_private_field(world):
    ids, call, ana = world["ids"], world["call"], world["ana"]
    profile = call(ana, "GET", f"/api/users/{ids['ben']}/profile").json()
    assert set(profile) == {
        "id",
        "first_name",
        "last_name",
        "position",
        "bio",
        "avatar_object_key",
        "avatar_url",
        "is_online",
        "friendship_status",
        "friendship_id",
    }
    # Her own profile route changes only her own row, and refuses an id or an email.
    response = call(ana, "PATCH", "/api/users/me", {"id": ids["ben"], "bio": "x"})
    assert response.status_code == 422
    response = call(ana, "PATCH", "/api/users/me", {"email": "ben@example.com"})
    assert response.status_code == 422
    assert sql("SELECT email, bio FROM users WHERE id = :id", id=ids["ben"]) == [
        ("ben@example.com", None)
    ]


def ticket(world, user) -> str:
    response = world["call"](user, "POST", "/api/ws/ticket")
    assert response.status_code == 200
    return response.json()["ticket"]


def socket(world, user, path: str = "/ws", query: str = "") -> ClientConnection:
    url = f"ws://{world['server']}{path}?ticket={ticket(world, user)}{query}"
    return connect(url, open_timeout=WAIT)


def test_ana_cannot_open_the_game_room_socket_of_ben_and_cara(world):
    with socket(world, world["ana"], "/ws/game", f"&room_id={world['ids']['room']}") as ws:
        with pytest.raises(ConnectionClosed):
            ws.recv(timeout=WAIT)
        assert (ws.close_code, ws.close_reason) == (1008, "Not a participant of this room")
    assert sql("SELECT count(*) FROM game_messages") == [(0,)]


def test_ana_cannot_mark_their_chat_read_or_delivered_on_her_socket(world):
    ids = world["ids"]
    before = their_data(ids)
    with socket(world, world["ben"]) as ben_ws, socket(world, world["ana"]) as ana_ws:
        frames = [
            {"type": "read", "conversation_id": ids["chat"], "last_message_id": ids["message"]},
            {"type": "delivered", "message_id": ids["message"]},
            {"type": "delivered", "payload": {"message_id": ids["message"]}},
        ]
        for frame in frames:
            ana_ws.send(json.dumps(frame))
        # Frames are handled in order: the pong comes after all three were handled.
        ana_ws.send(json.dumps({"type": "ping"}))
        assert json.loads(ana_ws.recv(timeout=WAIT))["type"] == "pong"
        # Ben heard nothing about it (no message_status, no conversation_updated).
        with pytest.raises(TimeoutError):
            ben_ws.recv(timeout=0.5)
    assert their_data(ids) == before
