"""Game disconnect handling (BE-33): seat persistence, snapshot resync, and bot privacy.

Per docs/game/turing-duel-rules.md (sections 3, 6, 9) and PO decision on PR #87:
1. Once a game starts, a participant who disconnects keeps their seat and saved marks.
2. No connection status of other participants is broadcast before results (preventing bot leaks).
3. The server timers continue moving the room on without waiting for disconnected players.
4. Reopening /ws/game delivers a full game_snapshot with current state, messages, and saved marks.
5. Returning players can chat during discussion and cast/update marks during voting.
6. A player with multiple open tabs can close one without breaking the session in the other.
"""

import json
import time
from collections.abc import Iterator

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
from websockets.sync.client import ClientConnection, connect

from app.auth import security

pytestmark = [needs_database, needs_redis]

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)
WAIT = 5


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
    sql("ALTER SEQUENCE game_participants_id_seq RESTART WITH 1001")
    yield client
    delete_test_keys(client)
    client.close()


def new_app(**overrides):
    settings = {
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "game_scheduler_enabled": False,
        "game_bot_probability": 0.0,
    }
    settings.update(overrides)
    return build_app(**settings)


@pytest.fixture
def server(clean) -> Iterator[str]:
    """One running API with the game's server loop off."""
    with running_server(new_app()) as address:
        yield address


# Helpers -------------------------------------------------------------------------------------


def sign_in(server: str, email: str) -> tuple[int, str]:
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :password_hash, true) RETURNING id",
        email=email,
        password_hash=PASSWORD_HASH,
    )
    response = httpx2.post(
        f"http://{server}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"X-Real-IP": f"10.9.0.{user_id % 250 + 1}"},
    )
    assert response.status_code == 200, response.text
    return user_id, response.json()["access_token"]


def issue_ticket(server: str, token: str) -> str:
    response = httpx2.post(
        f"http://{server}/api/ws/ticket",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


def join_and_start(server: str, *tokens: str) -> int:
    """Join users into a room and start the match (moves to discussion)."""
    room_id = None
    for token in tokens:
        res = httpx2.post(
            f"http://{server}/api/game/queue/join",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code in (200, 202), res.text
        room_id = res.json()["room_id"]

    start = httpx2.post(
        f"http://{server}/api/game/rooms/{room_id}/start",
        headers={"Authorization": f"Bearer {tokens[0]}"},
    )
    assert start.status_code == 200, start.text
    return room_id


def open_socket(server: str, token: str, room_id: int) -> ClientConnection:
    ticket = issue_ticket(server, token)
    ws = connect(f"ws://{server}/ws/game?ticket={ticket}&room_id={room_id}")
    return ws


def recv_snapshot(ws: ClientConnection) -> dict:
    frame = json.loads(ws.recv(timeout=WAIT))
    assert frame["type"] == "game_snapshot"
    return frame["payload"]


def nothing_arrives(ws: ClientConnection, seconds: float = 0.5) -> bool:
    try:
        ws.recv(timeout=seconds)
    except TimeoutError:
        return True
    return False


def wait_until_finished(server: str, token: str, room_id: int, timeout: float = 6.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        room = httpx2.get(
            f"http://{server}/api/game/rooms/{room_id}",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        if room["state"] == "finished":
            return
        time.sleep(0.05)
    raise AssertionError("the room did not finish")


def put_room_in(room_id: int, state: str, *, voting_past: bool = False) -> None:
    """Simulate server clock progressing room phase."""
    times = {
        "discussion": "started_at = now()",
        "voting": (
            "voting_started_at = now() - interval '1 hour'"
            if voting_past
            else "voting_started_at = now()"
        ),
        "finished": "finished_at = now()",
    }
    sql(
        f"UPDATE game_rooms SET state = CAST(:state AS game_room_state), {times[state]}"
        " WHERE id = :rid",
        state=state,
        rid=room_id,
    )


# Tests ---------------------------------------------------------------------------------------


def test_disconnect_in_discussion_preserves_seat_and_allows_chat_on_reconnect(server: str) -> None:
    """Disconnecting in discussion does not lose the seat. Reconnecting delivers snapshot and
    allows continuing the chat without errors.
    """
    _, alice_tok = sign_in(server, "alice@example.com")
    _, bob_tok = sign_in(server, "bob@example.com")
    room_id = join_and_start(server, alice_tok, bob_tok)

    # Both open /ws/game and read snapshots
    alice_ws = open_socket(server, alice_tok, room_id)
    bob_ws = open_socket(server, bob_tok, room_id)
    recv_snapshot(alice_ws)
    recv_snapshot(bob_ws)

    # Alice sends a message
    alice_ws.send(json.dumps({"type": "chat_message", "payload": {"text": "hello before drop"}}))
    msg1 = json.loads(bob_ws.recv(timeout=WAIT))
    assert msg1["type"] == "game_message"
    assert msg1["payload"]["text"] == "hello before drop"

    # Alice disconnects (socket closes)
    alice_ws.close()

    # Bob's connection is undisturbed; Bob can chat
    bob_ws.send(json.dumps({"type": "chat_message", "payload": {"text": "still here"}}))
    bob_echo = json.loads(bob_ws.recv(timeout=WAIT))
    assert bob_echo["type"] == "game_message"
    assert bob_echo["payload"]["text"] == "still here"

    # Alice reconnects with a fresh ticket
    alice_ws2 = open_socket(server, alice_tok, room_id)
    snap = recv_snapshot(alice_ws2)
    assert snap["room"]["state"] == "discussion"
    texts = [m["text"] for m in snap["messages"]]
    assert "hello before drop" in texts
    assert "still here" in texts

    # Alice chats again; Bob receives it
    alice_ws2.send(json.dumps({"type": "chat_message", "payload": {"text": "reconnected!"}}))
    msg3 = json.loads(bob_ws.recv(timeout=WAIT))
    assert msg3["type"] == "game_message"
    assert msg3["payload"]["text"] == "reconnected!"

    alice_ws2.close()
    bob_ws.close()


def test_disconnect_in_voting_preserves_marks_and_allows_voting_on_reconnect(server: str) -> None:
    """Disconnecting during voting keeps saved marks. Reconnecting restores marks in snapshot and
    allows changing votes before the phase ends.
    """
    _, alice_tok = sign_in(server, "alice@example.com")
    _, bob_tok = sign_in(server, "bob@example.com")
    room_id = join_and_start(server, alice_tok, bob_tok)

    # Move room to voting
    put_room_in(room_id, "voting")

    alice_ws = open_socket(server, alice_tok, room_id)
    alice_snap = recv_snapshot(alice_ws)
    bob_label_num = next(p["id"] for p in alice_snap["room"]["participants"] if not p["is_you"])

    # Alice votes: Bob is a bot
    v1 = httpx2.post(
        f"http://{server}/api/game/rooms/{room_id}/votes",
        json={"target_participant_id": bob_label_num, "guess": "bot"},
        headers={"Authorization": f"Bearer {alice_tok}"},
    )
    assert v1.status_code == 200, v1.text

    # Alice disconnects
    alice_ws.close()

    # Alice reconnects
    alice_ws2 = open_socket(server, alice_tok, room_id)
    snap2 = recv_snapshot(alice_ws2)
    assert snap2["room"]["state"] == "voting"
    # Alice's saved mark is present in snapshot
    assert snap2["my_votes"] == [{"target_participant_id": bob_label_num, "guess": "bot"}]

    # Alice changes her mark to human
    v2 = httpx2.post(
        f"http://{server}/api/game/rooms/{room_id}/votes",
        json={"target_participant_id": bob_label_num, "guess": "human"},
        headers={"Authorization": f"Bearer {alice_tok}"},
    )
    assert v2.status_code == 200, v2.text

    # Move room to finished
    put_room_in(room_id, "finished")
    res = httpx2.get(
        f"http://{server}/api/game/rooms/{room_id}/results",
        headers={"Authorization": f"Bearer {alice_tok}"},
    )
    assert res.status_code == 200
    alice_ws2.close()


def test_disconnected_player_who_never_reconnects_keeps_seat_and_default_marks(clean) -> None:
    """A player who disconnects and never reconnects keeps their seat and preset 'human' marks,
    which are evaluated at match end by the server voting tick.
    """
    app = new_app(game_scheduler_enabled=True, game_voting_sec=0.5, game_tick_interval_sec=0.04)
    with running_server(app) as srv:
        _, alice_tok = sign_in(srv, "alice@example.com")
        _, bob_tok = sign_in(srv, "bob@example.com")
        room_id = join_and_start(srv, alice_tok, bob_tok)

        alice_ws = open_socket(srv, alice_tok, room_id)
        recv_snapshot(alice_ws)
        # Alice drops immediately and never returns
        alice_ws.close()

        # Move to voting with voting_started_at in the past so the server clock finishes it via
        # _tick_voting_room -> _store_scores.
        put_room_in(room_id, "voting", voting_past=True)
        wait_until_finished(srv, bob_tok, room_id)

        # Bob fetches results; Alice kept her seat and preset 'human' mark on Bob (+1 each -> draw).
        res = httpx2.get(
            f"http://{srv}/api/game/rooms/{room_id}/results",
            headers={"Authorization": f"Bearer {bob_tok}"},
        )
        assert res.status_code == 200
        results = res.json()
        assert results["state"] == "finished"
        assert results["is_draw"] is True
        assert results["winner_participant_ids"] == []
        assert len(results["participants"]) == 2
        assert all(p["score"] == 1 and p["outcome"] == "draw" for p in results["participants"])


def test_closing_one_tab_of_multiple_tabs_does_not_break_session(server: str) -> None:
    """Closing one tab does not disrupt the active session or remaining tabs."""
    _, alice_tok = sign_in(server, "alice@example.com")
    _, bob_tok = sign_in(server, "bob@example.com")
    room_id = join_and_start(server, alice_tok, bob_tok)

    # Alice opens Tab 1 and Tab 2
    alice_tab1 = open_socket(server, alice_tok, room_id)
    recv_snapshot(alice_tab1)
    alice_tab2 = open_socket(server, alice_tok, room_id)
    recv_snapshot(alice_tab2)

    bob_ws = open_socket(server, bob_tok, room_id)
    recv_snapshot(bob_ws)

    # Alice closes Tab 1
    alice_tab1.close()

    # Tab 2 remains operational: sends and receives chat
    alice_tab2.send(json.dumps({"type": "chat_message", "payload": {"text": "from tab 2"}}))
    echo = json.loads(alice_tab2.recv(timeout=WAIT))
    assert echo["type"] == "game_message"
    assert echo["payload"]["text"] == "from tab 2"

    bob_msg = json.loads(bob_ws.recv(timeout=WAIT))
    assert bob_msg["type"] == "game_message"
    assert bob_msg["payload"]["text"] == "from tab 2"

    alice_tab2.close()
    bob_ws.close()


def test_no_peer_connection_status_event_leaked_on_disconnect(server: str) -> None:
    """Peer connection/disconnection events must NOT be sent before results to prevent leaking
    bot identities (rules, section 9).
    """
    _, alice_tok = sign_in(server, "alice@example.com")
    _, bob_tok = sign_in(server, "bob@example.com")
    room_id = join_and_start(server, alice_tok, bob_tok)

    alice_ws = open_socket(server, alice_tok, room_id)
    recv_snapshot(alice_ws)
    bob_ws = open_socket(server, bob_tok, room_id)
    recv_snapshot(bob_ws)

    # Alice disconnects and reconnects
    alice_ws.close()
    alice_ws2 = open_socket(server, alice_tok, room_id)
    recv_snapshot(alice_ws2)

    # Check Bob's socket: no frame (such as player_connection) arrives on disconnect or reconnect
    assert nothing_arrives(bob_ws)

    alice_ws2.close()
    bob_ws.close()
