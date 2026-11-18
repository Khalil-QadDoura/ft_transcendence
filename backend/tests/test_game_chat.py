"""The room socket /ws/game (BE-09): the shared ticket check, who may connect, the snapshot on
every (re)connect, chat during the discussion, the chat history, and races.

Real PostgreSQL, Redis and uvicorn (conftest.running_server) with a real WebSocket client, like
the browser's. The users are made up: added straight to the database and logged in through the
real /api/auth/login. The game's server loop is off unless a test needs it; the tests move a
room between phases with SQL instead, so nothing depends on timing.
"""

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx2
import pytest
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
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from app.auth import security
from app.game import chat
from app.game import repo as game_repo
from app.game import service as game_service
from app.game.constants import MAX_ID, MESSAGE_MAX_LENGTH, PLAYER_LABELS, label_number

pytestmark = [needs_database, needs_redis]

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)  # slow on purpose: made once for every user
WAIT = 5  # seconds a test waits for a frame that must come
NOT_A_PARTICIPANT = "Not a participant of this room"


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


def delete_test_keys(client: redis.Redis) -> None:
    for pattern in ("game:*", "ws:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


@pytest.fixture
def clean() -> Iterator[redis.Redis]:
    """No game, no user and no game or ws Redis key before and after each test."""
    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    delete_test_keys(client)
    sql("TRUNCATE game_votes, game_messages, game_participants, game_rooms RESTART IDENTITY")
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    # Database participant ids from 1001: a database id sent where a label number (1-5)
    # belongs can never pass for one by chance.
    sql("ALTER SEQUENCE game_participants_id_seq RESTART WITH 1001")
    yield client
    delete_test_keys(client)
    client.close()


def new_app(**overrides):
    settings = {"database_url": TEST_DATABASE_URL, "redis_url": TEST_REDIS_URL}
    settings.update({"game_bot_probability": 0.0, **overrides})
    return build_app(**settings)


@pytest.fixture
def server(clean) -> Iterator[str]:
    """One running API with the game's server loop off. Gives its address."""
    with running_server(new_app()) as address:
        yield address


# Helpers -------------------------------------------------------------------------------------


def sign_in(server: str, email: str) -> tuple[int, str]:
    """A made-up verified account, logged in. Returns its id and its access token."""
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :password_hash, true) RETURNING id",
        email=email,
        password_hash=PASSWORD_HASH,
    )
    response = httpx2.post(
        f"http://{server}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"X-Real-IP": f"10.9.0.{user_id % 250 + 1}"},  # its own login rate limit
    )
    assert response.status_code == 200, response.text
    return user_id, response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def join(server: str, token: str) -> int:
    response = httpx2.post(f"http://{server}/api/game/queue/join", headers=bearer(token))
    assert response.status_code == 202, response.text
    return response.json()["room_id"]


def start(server: str, token: str, room_id: int) -> dict:
    response = httpx2.post(f"http://{server}/api/game/rooms/{room_id}/start", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


def get_room(server: str, token: str, room_id: int) -> dict:
    response = httpx2.get(f"http://{server}/api/game/rooms/{room_id}", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


def my_label(server: str, token: str, room_id: int) -> str:
    return next(p for p in get_room(server, token, room_id)["participants"] if p["is_you"])[
        "display_label"
    ]


def new_ticket(server: str, token: str) -> str:
    response = httpx2.post(f"http://{server}/api/ws/ticket", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


def open_room_socket(server: str, query: str) -> ClientConnection:
    """A WebSocket client on /ws/game<query>, e.g. query="?ticket=...&room_id=7"."""
    return connect(f"ws://{server}/ws/game{query}", open_timeout=WAIT)


def room_socket(server: str, token: str, room_id: object) -> ClientConnection:
    """What the game screen does: a new ticket, then /ws/game?ticket=<it>&room_id=<room>."""
    return open_room_socket(server, f"?ticket={new_ticket(server, token)}&room_id={room_id}")


@contextmanager
def user_socket(server: str, token: str) -> Iterator[ClientConnection]:
    """The BE-06 socket /ws, which the lobby uses."""
    with connect(f"ws://{server}/ws?ticket={new_ticket(server, token)}", open_timeout=WAIT) as ws:
        ws.send(json.dumps({"type": "ping"}))
        assert next_frame(ws)["type"] == "pong"  # it listens on the user's channel by now
        yield ws


def next_frame(ws: ClientConnection) -> dict:
    return json.loads(ws.recv(timeout=WAIT))


def snapshot(ws: ClientConnection) -> dict:
    """The first frame of a room socket must be the snapshot. Returns its payload."""
    frame = next_frame(ws)
    assert frame["type"] == "game_snapshot", frame
    return frame["payload"]


def wait_for(ws: ClientConnection, event_type: str) -> dict:
    """The next frame of this type (others are skipped). Returns its payload."""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        frame = next_frame(ws)
        if frame["type"] == event_type:
            return frame["payload"]
    raise AssertionError(f"no {event_type} frame")


def closed_with(ws: ClientConnection) -> tuple[int, str]:
    """Wait until the server closes the socket; returns its close code and reason."""
    with pytest.raises(ConnectionClosed):
        ws.recv(timeout=WAIT)
    return ws.close_code, ws.close_reason


def nothing_arrives(ws: ClientConnection, seconds: float = 0.5) -> bool:
    try:
        ws.recv(timeout=seconds)
    except TimeoutError:
        return True
    return False


def say(ws: ClientConnection, text: object) -> None:
    ws.send(json.dumps({"type": "chat_message", "text": text}))


def saved_messages(room_id: int) -> list[tuple]:
    return sql(
        "SELECT m.text, p.display_label FROM game_messages m"
        " JOIN game_participants p ON p.id = m.participant_id"
        " WHERE m.room_id = :room_id ORDER BY m.id",
        room_id=room_id,
    )


def participant_id(room_id: int, user_id: int) -> int:
    [(pid,)] = sql(
        "SELECT id FROM game_participants WHERE room_id = :room_id AND user_id = :user_id",
        room_id=room_id,
        user_id=user_id,
    )
    return pid


def set_state(room_id: int, state: str, **times: str) -> None:
    """Move a room to another phase, as the server loop would. `times` sets timestamp columns
    from SQL expressions, e.g. voting_started_at="now()"."""
    columns = ", ".join(f"{name} = {expression}" for name, expression in times.items())
    sql(
        f"UPDATE game_rooms SET state = :state{', ' + columns if columns else ''} WHERE id = :id",
        state=state,
        id=room_id,
    )


def two_player_room(server: str) -> tuple[int, tuple[int, str], tuple[int, str]]:
    """Alice and Bob in one room, still waiting. Returns the room id and both (id, token)."""
    alice = sign_in(server, "alice@example.com")
    bob = sign_in(server, "bob@example.com")
    room_id = join(server, alice[1])
    assert join(server, bob[1]) == room_id
    return room_id, alice, bob


def discussion_room(server: str) -> tuple[int, tuple[int, str], tuple[int, str]]:
    """Alice and Bob in one room, in the discussion (Alice pressed Start now)."""
    room_id, alice, bob = two_player_room(server)
    assert start(server, alice[1], room_id)["state"] == "discussion"
    return room_id, alice, bob


# The ticket check, shared with /ws ----------------------------------------------------------


def test_room_socket_needs_a_valid_ticket(server):
    room_id, _, _ = two_player_room(server)
    for query in (
        f"?room_id={room_id}",
        f"?ticket=&room_id={room_id}",
        "?ticket=made-up&room_id=1",
    ):
        with open_room_socket(server, query) as ws:
            assert closed_with(ws) == (1008, "Invalid or expired ticket")


def test_room_socket_checks_token_version_like_ws(server):
    room_id, (alice_id, alice_token), _ = two_player_room(server)
    ticket = new_ticket(server, alice_token)
    sql("UPDATE users SET token_version = token_version + 1 WHERE id = :id", id=alice_id)
    with open_room_socket(server, f"?ticket={ticket}&room_id={room_id}") as ws:
        assert closed_with(ws) == (1008, "Invalid or expired ticket")


def test_a_ticket_used_on_ws_does_not_open_the_room_socket(server):
    room_id, (_, alice_token), _ = two_player_room(server)
    ticket = new_ticket(server, alice_token)
    with connect(f"ws://{server}/ws?ticket={ticket}", open_timeout=WAIT) as ws:
        ws.send(json.dumps({"type": "ping"}))
        assert next_frame(ws)["type"] == "pong"
        with open_room_socket(server, f"?ticket={ticket}&room_id={room_id}") as game_ws:
            assert closed_with(game_ws) == (1008, "Invalid or expired ticket")


# Who may connect ----------------------------------------------------------------------------


def test_room_socket_closes_1008_for_anyone_outside_the_room(server):
    room_id, (_, alice_token), _ = two_player_room(server)
    _, carol_token = sign_in(server, "carol@example.com")
    _, dave_token = sign_in(server, "dave@example.com")

    with room_socket(server, carol_token, room_id) as ws:  # Carol is in no room
        assert closed_with(ws) == (1008, NOT_A_PARTICIPANT)

    # Once Alice's game has started, Dave's join opens another room.
    set_state(room_id, "discussion", discussion_started_at="now()")
    other_room = join(server, dave_token)
    assert other_room != room_id
    with room_socket(server, dave_token, room_id) as ws:  # a player of another room
        assert closed_with(ws) == (1008, NOT_A_PARTICIPANT)
    with room_socket(server, alice_token, other_room) as ws:  # and the other way round
        assert closed_with(ws) == (1008, NOT_A_PARTICIPANT)

    # An unknown room, then ids that are no room id at all ("%EF%BC%91" is a full-width 1).
    for bad in ("999999", "", "abc", "0", "-1", "1.5", str(MAX_ID + 1), "%EF%BC%91", "1%200"):
        with room_socket(server, alice_token, bad) as ws:
            assert closed_with(ws) == (1008, NOT_A_PARTICIPANT), bad
    with open_room_socket(server, f"?ticket={new_ticket(server, alice_token)}") as ws:
        assert closed_with(ws) == (1008, NOT_A_PARTICIPANT)  # no room_id at all

    with room_socket(server, alice_token, room_id) as ws:  # Alice herself is let in
        assert snapshot(ws)["room"]["id"] == room_id


def test_a_player_who_left_the_waiting_room_is_no_longer_let_in(server):
    room_id, (_, alice_token), (_, bob_token) = two_player_room(server)
    response = httpx2.delete(f"http://{server}/api/game/queue/leave", headers=bearer(bob_token))
    assert response.status_code == 204
    with room_socket(server, bob_token, room_id) as ws:
        assert closed_with(ws) == (1008, NOT_A_PARTICIPANT)
    with room_socket(server, alice_token, room_id) as ws:
        assert snapshot(ws)["room"]["participant_count"] == 1


# The snapshot -------------------------------------------------------------------------------


def test_snapshot_comes_first_with_state_participants_and_phase_end(server):
    room_id, (_, alice_token), (_, bob_token) = two_player_room(server)
    alice_label, bob_label = (
        my_label(server, alice_token, room_id),
        my_label(server, bob_token, room_id),
    )

    with room_socket(server, alice_token, room_id) as ws:
        snap = snapshot(ws)
    assert set(snap) == {"room", "messages", "my_votes"}
    room = snap["room"]
    rest_room = get_room(server, alice_token, room_id)
    assert set(room) == set(rest_room)  # the same shape as GET /api/game/rooms/{id}
    assert room["id"] == room_id
    assert room["state"] == "waiting"
    assert room["participant_count"] == 2
    assert room["phase_ends_at"] == room["room_expires_at"] == rest_room["room_expires_at"]
    # Every participant by label number only, the same fields for all, mine marked "is_you".
    assert room["my_participant_id"] == label_number(alice_label)
    assert sorted(room["participants"], key=lambda p: p["id"]) == sorted(
        [
            {"id": label_number(alice_label), "display_label": alice_label, "is_you": True},
            {"id": label_number(bob_label), "display_label": bob_label, "is_you": False},
        ],
        key=lambda p: p["id"],
    )
    assert snap["messages"] == [] and snap["my_votes"] == []

    start(server, bob_token, room_id)
    with room_socket(server, alice_token, room_id) as ws:
        room = snapshot(ws)["room"]
    assert room["state"] == "discussion"
    assert room["phase_ends_at"] == get_room(server, alice_token, room_id)["phase_ends_at"]


def test_snapshot_shows_only_my_own_marks_by_label_number(server):
    room_id, (alice_id, alice_token), (bob_id, bob_token) = discussion_room(server)
    _, carol_token = sign_in(server, "carol@example.com")
    other_room = join(server, carol_token)
    set_state(room_id, "voting", voting_started_at="now()")
    alice_pid, bob_pid = participant_id(room_id, alice_id), participant_id(room_id, bob_id)
    vote = (
        "INSERT INTO game_votes (room_id, voter_participant_id, target_participant_id, guess)"
        " VALUES (:room_id, :voter, :target, :guess)"
    )
    sql(vote, room_id=room_id, voter=alice_pid, target=bob_pid, guess="bot")
    sql(vote, room_id=room_id, voter=bob_pid, target=alice_pid, guess="human")
    # A bad row pointing into another room (BE-10 refuses to save one) is never shown.
    carol_pid = sql("SELECT id FROM game_participants WHERE room_id = :r", r=other_room)[0][0]
    sql(vote, room_id=room_id, voter=alice_pid, target=carol_pid, guess="human")

    bob_number = label_number(my_label(server, bob_token, room_id))
    alice_number = label_number(my_label(server, alice_token, room_id))
    with room_socket(server, alice_token, room_id) as ws:
        snap = snapshot(ws)
    assert snap["my_votes"] == [{"target_participant_id": bob_number, "guess": "bot"}]
    assert snap["room"]["state"] == "voting"
    assert snap["room"]["phase_ends_at"] == get_room(server, alice_token, room_id)["phase_ends_at"]
    with room_socket(server, bob_token, room_id) as ws:
        assert snapshot(ws)["my_votes"] == [
            {"target_participant_id": alice_number, "guess": "human"}
        ]


def test_resync_after_reconnect(server):
    room_id, (_, alice_token), (_, bob_token) = discussion_room(server)
    alice_label, bob_label = (
        my_label(server, alice_token, room_id),
        my_label(server, bob_token, room_id),
    )
    with room_socket(server, alice_token, room_id) as alice_ws:
        first = snapshot(alice_ws)
        say(alice_ws, "hello, I am typing from my laptop")
        wait_for(alice_ws, "game_message")
    # Alice's page reloads. While she is away, Bob writes.
    with room_socket(server, bob_token, room_id) as bob_ws:
        snapshot(bob_ws)
        say(bob_ws, "where did you go?")
        wait_for(bob_ws, "game_message")

        with room_socket(server, alice_token, room_id) as alice_ws:  # a new ticket, as always
            again = snapshot(alice_ws)
            assert again["room"] == first["room"]  # same state, same phase end
            assert [
                (m["participant_id"], m["display_label"], m["text"]) for m in again["messages"]
            ] == [
                (label_number(alice_label), alice_label, "hello, I am typing from my laptop"),
                (label_number(bob_label), bob_label, "where did you go?"),
            ]
            # After the snapshot, the live chat goes on.
            say(bob_ws, "welcome back")
            assert wait_for(alice_ws, "game_message")["text"] == "welcome back"


def test_snapshot_carries_only_the_recent_messages(server):
    room_id, (alice_id, alice_token), _ = discussion_room(server)
    pid = participant_id(room_id, alice_id)
    sql(
        "INSERT INTO game_messages (room_id, participant_id, text)"
        " SELECT :room_id, :pid, 'line ' || n FROM generate_series(1, 60) AS n",
        room_id=room_id,
        pid=pid,
    )
    with room_socket(server, alice_token, room_id) as ws:
        texts = [m["text"] for m in snapshot(ws)["messages"]]
    assert texts == [f"line {n}" for n in range(11, 61)]  # the newest 50, oldest first


# Chat ---------------------------------------------------------------------------------------


def test_chat_in_the_discussion_reaches_every_human_and_is_saved(server):
    room_id, (alice_id, alice_token), (_, bob_token) = discussion_room(server)
    alice_label = my_label(server, alice_token, room_id)
    with (
        room_socket(server, alice_token, room_id) as alice_ws,
        room_socket(server, bob_token, room_id) as bob_ws,
        user_socket(server, bob_token) as bob_lobby_ws,
    ):
        snapshot(alice_ws)
        snapshot(bob_ws)
        say(alice_ws, "  hi all, who is real here?  ")
        expected_text = "hi all, who is real here?"  # surrounding spaces trimmed
        for ws in (alice_ws, bob_ws, bob_lobby_ws):  # the author's own tab too, and /ws
            message = wait_for(ws, "game_message")
            assert set(message) == {"id", "participant_id", "display_label", "text"}
            assert message["participant_id"] == label_number(alice_label)
            assert message["display_label"] == alice_label
            assert message["text"] == expected_text
    assert saved_messages(room_id) == [(expected_text, alice_label)]
    [(author_pid,)] = sql("SELECT participant_id FROM game_messages")
    assert author_pid == participant_id(room_id, alice_id)  # the database keeps the real id


def test_chat_text_can_also_come_inside_payload(server):
    room_id, (_, alice_token), _ = discussion_room(server)
    with room_socket(server, alice_token, room_id) as ws:
        snapshot(ws)
        ws.send(json.dumps({"type": "chat_message", "payload": {"text": "in a payload"}}))
        assert wait_for(ws, "game_message")["text"] == "in a payload"


def test_chat_outside_the_discussion_is_refused_and_not_saved(server):
    room_id, (_, alice_token), (_, bob_token) = two_player_room(server)
    with room_socket(server, bob_token, room_id) as bob_ws:
        snapshot(bob_ws)
        for state, times in (
            ("waiting", {}),
            ("discussion", {"discussion_started_at": "now() - interval '121 seconds'"}),
            ("voting", {"voting_started_at": "now()"}),
            ("finished", {"finished_at": "now()"}),
            ("closed", {}),
        ):
            set_state(room_id, state, **times)
            with room_socket(server, alice_token, room_id) as alice_ws:
                assert snapshot(alice_ws)["room"]["state"] == state
                say(alice_ws, "is anyone there?")
                assert next_frame(alice_ws) == {
                    "type": "game_error",
                    "payload": {"detail": "Chat is open only during the discussion"},
                }, state
        assert nothing_arrives(bob_ws)
    assert saved_messages(room_id) == []


def test_bad_chat_text_is_refused_and_the_socket_stays_usable(server):
    room_id, (_, alice_token), _ = discussion_room(server)
    with room_socket(server, alice_token, room_id) as ws:
        snapshot(ws)
        too_long = "x" * (MESSAGE_MAX_LENGTH + 1)
        for text, detail in (
            ("", "Message is empty"),
            ("   \n ", "Message is empty"),
            (None, "Message is empty"),
            (42, "Message is empty"),
            (["a"], "Message is empty"),
            (too_long, f"Message is longer than {MESSAGE_MAX_LENGTH} characters"),
            ("a\u0000b", "Message has characters that cannot be saved"),
        ):
            say(ws, text)
            assert next_frame(ws) == {"type": "game_error", "payload": {"detail": detail}}, text
        ws.send('{"type": "chat_message"}')  # no text at all
        assert next_frame(ws)["payload"] == {"detail": "Message is empty"}
        ws.send('{"type": "chat_message", "text": "\\ud800"}')  # a lone surrogate
        assert next_frame(ws)["payload"] == {
            "detail": "Message has characters that cannot be saved"
        }
        # Unknown frames and non-JSON are ignored; ping still answers; a full-length line works.
        ws.send("not json")
        ws.send(json.dumps({"type": "vote", "text": "x"}))
        ws.send(json.dumps({"type": "ping"}))
        assert next_frame(ws) == {"type": "pong", "payload": None}
        say(ws, "y" * MESSAGE_MAX_LENGTH)
        assert wait_for(ws, "game_message")["text"] == "y" * MESSAGE_MAX_LENGTH
    assert [text for text, _ in saved_messages(room_id)] == ["y" * MESSAGE_MAX_LENGTH]


# The history: GET /api/game/rooms/{id}/messages -----------------------------------------------


def test_history_is_for_the_room_participants_only(server):
    room_id, (_, alice_token), _ = discussion_room(server)
    _, carol_token = sign_in(server, "carol@example.com")
    other_room = join(server, carol_token)  # Carol is in a room, but not this one
    url = f"http://{server}/api/game/rooms"

    assert httpx2.get(f"{url}/{room_id}/messages").status_code == 401
    assert httpx2.get(f"{url}/{room_id}/messages", headers=bearer(carol_token)).status_code == 403
    assert (
        httpx2.get(f"{url}/{other_room}/messages", headers=bearer(alice_token)).status_code == 403
    )
    missing = httpx2.get(f"{url}/999999/messages", headers=bearer(alice_token))
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "404", "detail": "Room not found"}}
    for bad in (
        f"{url}/0/messages",
        f"{url}/{MAX_ID + 1}/messages",
        f"{url}/abc/messages",
        f"{url}/{room_id}/messages?before_id=0",
        f"{url}/{room_id}/messages?before_id={MAX_ID + 1}",
        f"{url}/{room_id}/messages?before_id=abc",
        f"{url}/{room_id}/messages?limit=0",
        f"{url}/{room_id}/messages?limit=101",
    ):
        assert httpx2.get(bad, headers=bearer(alice_token)).status_code == 422, bad
    ok = httpx2.get(f"{url}/{room_id}/messages", headers=bearer(alice_token))
    assert ok.status_code == 200
    assert ok.json() == {"items": [], "prev_before_id": None}


def test_history_pages_go_back_from_the_newest(server):
    room_id, (_, alice_token), (_, bob_token) = discussion_room(server)
    _, carol_token = sign_in(server, "carol@example.com")
    _, dan_token = sign_in(server, "dan@example.com")
    other_room = join(server, carol_token)
    assert join(server, dan_token) == other_room
    start(server, carol_token, other_room)
    with (
        room_socket(server, alice_token, room_id) as alice_ws,
        room_socket(server, bob_token, room_id) as bob_ws,
        room_socket(server, carol_token, other_room) as carol_ws,
    ):
        for ws in (alice_ws, bob_ws, carol_ws):
            snapshot(ws)
        for n, ws in enumerate((alice_ws, bob_ws, alice_ws, bob_ws, alice_ws), start=1):
            say(ws, f"message {n}")
            wait_for(ws, "game_message")
            say(carol_ws, f"other room {n}")  # never in this room's history
            wait_for(carol_ws, "game_message")

    def page(**params) -> dict:
        response = httpx2.get(
            f"http://{server}/api/game/rooms/{room_id}/messages",
            params=params,
            headers=bearer(bob_token),
        )
        assert response.status_code == 200, response.text
        return response.json()

    labels = {
        "alice": my_label(server, alice_token, room_id),
        "bob": my_label(server, bob_token, room_id),
    }
    everything = page()
    assert [m["text"] for m in everything["items"]] == [f"message {n}" for n in range(1, 6)]
    assert everything["prev_before_id"] is None
    for item, author in zip(
        everything["items"], ("alice", "bob", "alice", "bob", "alice"), strict=True
    ):
        assert item["display_label"] == labels[author]
        assert item["participant_id"] == label_number(labels[author])

    newest = page(limit=2)
    assert [m["text"] for m in newest["items"]] == ["message 4", "message 5"]
    middle = page(limit=2, before_id=newest["prev_before_id"])
    assert [m["text"] for m in middle["items"]] == ["message 2", "message 3"]
    oldest = page(limit=2, before_id=middle["prev_before_id"])
    assert [m["text"] for m in oldest["items"]] == ["message 1"]
    assert oldest["prev_before_id"] is None
    exactly_all = page(limit=5)  # a full page that holds the whole chat: nothing older
    assert len(exactly_all["items"]) == 5 and exactly_all["prev_before_id"] is None


# The lobby's events stay on the user's channel ----------------------------------------------


def test_lobby_events_reach_ws_and_the_room_socket_unchanged(server):
    _, alice_token = sign_in(server, "alice@example.com")
    _, bob_token = sign_in(server, "bob@example.com")
    room_id = join(server, alice_token)
    with (
        user_socket(server, alice_token) as lobby_ws,
        room_socket(server, alice_token, room_id) as game_ws,
    ):
        snapshot(game_ws)
        assert join(server, bob_token) == room_id
        bob_label = my_label(server, bob_token, room_id)
        for ws in (lobby_ws, game_ws):
            joined = wait_for(ws, "game_participant_joined")
            assert set(joined) == {"room_id", "participant", "participant_count", "room_expires_at"}
            assert joined["room_id"] == room_id and joined["participant_count"] == 2
            assert set(joined["participant"]) == {"id", "display_label"}
            assert joined["participant"]["display_label"] == bob_label

        httpx2.delete(f"http://{server}/api/game/queue/leave", headers=bearer(bob_token))
        for ws in (lobby_ws, game_ws):
            left = wait_for(ws, "game_participant_left")
            assert left["room_id"] == room_id and left["participant_count"] == 1

        assert join(server, bob_token) == room_id
        start(server, alice_token, room_id)
        for ws in (lobby_ws, game_ws):
            started = wait_for(ws, "game_started")
            assert set(started) == {"room_id", "state", "phase_ends_at"}
            assert started["room_id"] == room_id and started["state"] == "discussion"


# Bots chat like humans ----------------------------------------------------------------------


def test_bot_lines_look_exactly_like_human_lines(clean, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(game_service.random, "randint", lambda a, b: 1)  # exactly one bot
    app = new_app(
        game_scheduler_enabled=True,
        game_bot_probability=1.0,
        game_bot_min_delay_sec=0.05,
        game_bot_max_delay_sec=0.08,
        game_tick_interval_sec=0.04,
        game_bot_chat_min_delay_sec=0.3,
        game_bot_chat_max_delay_sec=0.6,
    )
    with running_server(app) as srv:
        _, alice_token = sign_in(srv, "alice@example.com")
        room_id = join(srv, alice_token)
        deadline = time.monotonic() + WAIT
        while get_room(srv, alice_token, room_id)["participant_count"] < 2:  # the bot joins
            assert time.monotonic() < deadline, "the bot never joined"
            time.sleep(0.05)
        start(srv, alice_token, room_id)
        with room_socket(srv, alice_token, room_id) as ws:
            snap = snapshot(ws)
            # Two participants, one a bot: nothing tells which.
            participants = snap["room"]["participants"]
            assert [set(p) for p in participants] == [{"id", "display_label", "is_you"}] * 2
            assert all(p["display_label"] in PLAYER_LABELS for p in participants)
            assert all(p["id"] == label_number(p["display_label"]) for p in participants)
            say(ws, "hello there")
            # A bot line may already be in the snapshot or come live: wait for both authors.
            lines = list(snap["messages"])
            while len({line["display_label"] for line in lines}) < 2 or not any(
                line["text"] == "hello there" for line in lines
            ):
                lines.append(wait_for(ws, "game_message"))
        for line in lines:
            assert set(line) == {"id", "participant_id", "display_label", "text"}
            assert line["participant_id"] == label_number(line["display_label"])
        history = httpx2.get(
            f"http://{srv}/api/game/rooms/{room_id}/messages", headers=bearer(alice_token)
        ).json()["items"]
        for line in lines:
            assert line in history


# Races --------------------------------------------------------------------------------------


def test_two_players_chatting_at_the_same_moment(server):
    room_id, (_, alice_token), (_, bob_token) = discussion_room(server)
    with (
        room_socket(server, alice_token, room_id) as alice_ws,
        room_socket(server, bob_token, room_id) as bob_ws,
    ):
        snapshot(alice_ws)
        snapshot(bob_ws)
        go = threading.Barrier(2)

        def send(ws: ClientConnection, text: str) -> None:
            go.wait()
            for n in range(5):
                say(ws, f"{text} {n}")

        threads = [
            threading.Thread(target=send, args=(alice_ws, "alice")),
            threading.Thread(target=send, args=(bob_ws, "bob")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        seen = {"alice": [], "bob": []}
        for name, ws in (("alice", alice_ws), ("bob", bob_ws)):
            while len(seen[name]) < 10:
                seen[name].append(wait_for(ws, "game_message"))

    # Both saw all ten. Live, two lines sent at the same moment can arrive in a different
    # order in two browsers; the id is the order they were saved in (history and snapshot).
    def by_id(messages: list[dict]) -> list[dict]:
        return sorted(messages, key=lambda m: m["id"])

    assert by_id(seen["alice"]) == by_id(seen["bob"])
    assert len({m["id"] for m in seen["alice"]}) == 10
    assert sorted(text for text, _ in saved_messages(room_id)) == sorted(
        m["text"] for m in seen["alice"]
    )


def room_in_discussion() -> tuple[int, SimpleNamespace]:
    """A room in the discussion with two humans, written straight to the database. The
    discussion starts now by this machine's clock, the one the chat checks."""
    [(alice_id,)] = sql(
        "INSERT INTO users (email, password_hash) VALUES ('a@example.com', 'x') RETURNING id"
    )
    [(bob_id,)] = sql(
        "INSERT INTO users (email, password_hash) VALUES ('b@example.com', 'x') RETURNING id"
    )
    [(room_id,)] = sql(
        "INSERT INTO game_rooms (target_size, state, room_expires_at, discussion_started_at)"
        " VALUES (5, 'discussion', :now, :now) RETURNING id",
        now=datetime.now(UTC),
    )
    for user_id, label in ((alice_id, "Player 2"), (bob_id, "Player 4")):
        sql(
            "INSERT INTO game_participants (room_id, user_id, display_label)"
            " VALUES (:room_id, :user_id, :label)",
            room_id=room_id,
            user_id=user_id,
            label=label,
        )
    return room_id, SimpleNamespace(id=alice_id)


async def stays_blocked(task: asyncio.Task, seconds: float = 0.4) -> bool:
    """True when the task is still waiting after `seconds`."""
    done, _ = await asyncio.wait({task}, timeout=seconds)
    return not done


def run_in_app(app, scenario) -> object:
    """Run `scenario()` (async) in this test, as code in an API process would run, then
    close the app's database and Redis connections."""

    async def run():
        try:
            return await scenario()
        finally:
            await app.state.engine.dispose()
            await app.state.redis.aclose()

    return asyncio.run(run())


def test_the_phase_change_waits_for_a_message_being_saved(clean, monkeypatch):
    """A message whose save started in the discussion is saved before the room moves on."""
    room_id, alice = room_in_discussion()
    app = new_app(game_discussion_sec=1.0)
    real_create_message = game_repo.create_message

    async def scenario():
        inside, release = asyncio.Event(), asyncio.Event()

        async def paused_create_message(*args, **kwargs):
            inside.set()  # the room is locked (FOR SHARE) and the clock said "discussion"
            await release.wait()
            return await real_create_message(*args, **kwargs)

        monkeypatch.setattr(game_repo, "create_message", paused_create_message)
        chatting = asyncio.create_task(chat.post_message(app, alice, room_id, "just in time"))
        await asyncio.wait_for(inside.wait(), WAIT)
        await asyncio.sleep(1.1)  # the discussion is over by the clock now
        ticking = asyncio.create_task(
            game_service.process_room_tick(
                app.state.session_factory, app.state.redis, app.state.settings, room_id
            )
        )
        assert await stays_blocked(ticking)  # the move to voting waits for the message
        release.set()
        assert await asyncio.wait_for(chatting, WAIT) is None  # saved and sent
        await asyncio.wait_for(ticking, WAIT)

    run_in_app(app, scenario)
    [(state, voting_started_at)] = sql(
        "SELECT state, voting_started_at FROM game_rooms WHERE id = :id", id=room_id
    )
    [(sent_at,)] = sql("SELECT sent_at FROM game_messages WHERE room_id = :id", id=room_id)
    assert state == "voting"
    assert sent_at < voting_started_at


def test_a_message_sent_during_the_phase_change_is_refused(clean):
    """The other order: the room is being moved to voting when the message comes."""
    room_id, alice = room_in_discussion()
    app = new_app()

    async def scenario():
        async with app.state.session_factory() as mover:
            room = await game_repo.get_room_for_update(mover, room_id)  # the server loop's lock
            chatting = asyncio.create_task(chat.post_message(app, alice, room_id, "too late"))
            assert await stays_blocked(chatting)  # the message waits for the phase change
            room.state = "voting"
            await mover.commit()
        return await asyncio.wait_for(chatting, WAIT)

    assert run_in_app(app, scenario) == chat.CHAT_CLOSED
    assert saved_messages(room_id) == []
