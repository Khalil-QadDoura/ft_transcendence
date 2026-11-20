"""Game disconnect handling (BE-33): seat grace period (30 s) and peer connection status.

When a participant's /ws/game socket drops, the seat is kept for a 30 s grace period in Redis.
Room peers receive `player_connection {participant_id, connected: false}`.
Reconnecting inside the grace period restores normal play and clears the grace key.
Reconnecting after the grace period expired marks the participant expired, refusing any
further chat messages with "Grace period expired". The player stays in the room and
phase timers run strictly on the server without blocking.
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
from app.game.constants import (
    DISCONNECT_GRACE_SEC,
    disconnect_at_key,
    disconnect_expired_key,
    disconnect_grace_key,
    label_number,
)

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
    settings = {"database_url": TEST_DATABASE_URL, "redis_url": TEST_REDIS_URL}
    settings.update({"game_bot_probability": 0.0, **overrides})
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


def participant_id(room_id: int, user_id: int) -> int:
    [(pid,)] = sql(
        "SELECT id FROM game_participants WHERE room_id = :room_id AND user_id = :user_id",
        room_id=room_id,
        user_id=user_id,
    )
    return pid


def new_ticket(server: str, token: str) -> str:
    response = httpx2.post(f"http://{server}/api/ws/ticket", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


def room_socket(server: str, token: str, room_id: object) -> ClientConnection:
    return connect(
        f"ws://{server}/ws/game?ticket={new_ticket(server, token)}&room_id={room_id}",
        open_timeout=WAIT,
    )


def next_frame(ws: ClientConnection) -> dict:
    return json.loads(ws.recv(timeout=WAIT))


def snapshot(ws: ClientConnection) -> dict:
    frame = next_frame(ws)
    assert frame["type"] == "game_snapshot", frame
    return frame["payload"]


def wait_for(ws: ClientConnection, event_type: str) -> dict:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        frame = next_frame(ws)
        if frame["type"] == event_type:
            return frame["payload"]
    raise AssertionError(f"no {event_type} frame")


def say(ws: ClientConnection, text: object) -> None:
    ws.send(json.dumps({"type": "chat_message", "text": text}))


def set_state(room_id: int, state: str, **times: str) -> None:
    columns = ", ".join(f"{name} = {expression}" for name, expression in times.items())
    sql(
        f"UPDATE game_rooms SET state = :state{', ' + columns if columns else ''} WHERE id = :id",
        state=state,
        id=room_id,
    )


def two_player_room(server: str) -> tuple[int, tuple[int, str], tuple[int, str]]:
    alice = sign_in(server, "alice@example.com")
    bob = sign_in(server, "bob@example.com")
    room_id = join(server, alice[1])
    assert join(server, bob[1]) == room_id
    return room_id, alice, bob


def discussion_room(server: str) -> tuple[int, tuple[int, str], tuple[int, str]]:
    room_id, alice, bob = two_player_room(server)
    assert start(server, alice[1], room_id)["state"] == "discussion"
    return room_id, alice, bob


# Tests ---------------------------------------------------------------------------------------


def test_peer_receives_player_connection_false_on_socket_close(server, clean: redis.Redis):
    room_id, (alice_id, alice_token), (_, bob_token) = discussion_room(server)
    alice_label = my_label(server, alice_token, room_id)
    alice_num = label_number(alice_label)
    alice_pid = participant_id(room_id, alice_id)

    with room_socket(server, bob_token, room_id) as bob_ws:
        snapshot(bob_ws)

        with room_socket(server, alice_token, room_id) as alice_ws:
            snapshot(alice_ws)
            # Bob sees Alice connected
            event_on_connect = wait_for(bob_ws, "player_connection")
            assert event_on_connect == {"participant_id": alice_num, "connected": True}

        # Alice closes her socket on exiting with block
        event = wait_for(bob_ws, "player_connection")
        assert event == {"participant_id": alice_num, "connected": False}

        # Verify Redis keys exist with grace TTL (30 s)
        ttl_pid = clean.ttl(disconnect_grace_key(room_id, alice_pid))
        ttl_num = clean.ttl(disconnect_grace_key(room_id, alice_num))
        assert 0 < ttl_pid <= DISCONNECT_GRACE_SEC
        assert 0 < ttl_num <= DISCONNECT_GRACE_SEC
        assert clean.exists(disconnect_at_key(room_id, alice_pid))
        assert clean.exists(disconnect_at_key(room_id, alice_num))


def test_reconnect_within_grace_period_restores_player(server, clean: redis.Redis):
    room_id, (alice_id, alice_token), (_, bob_token) = discussion_room(server)
    alice_label = my_label(server, alice_token, room_id)
    alice_num = label_number(alice_label)
    alice_pid = participant_id(room_id, alice_id)

    with room_socket(server, bob_token, room_id) as bob_ws:
        snapshot(bob_ws)

        with room_socket(server, alice_token, room_id) as alice_ws:
            snapshot(alice_ws)
            wait_for(bob_ws, "player_connection")

        # Disconnected Alice
        disc_event = wait_for(bob_ws, "player_connection")
        assert disc_event == {"participant_id": alice_num, "connected": False}
        assert clean.exists(disconnect_grace_key(room_id, alice_pid))

        # Reconnect Alice within 30 s
        with room_socket(server, alice_token, room_id) as alice_ws2:
            snap = snapshot(alice_ws2)
            assert snap["room"]["id"] == room_id

            # Bob receives connected: True
            rec_event = wait_for(bob_ws, "player_connection")
            assert rec_event == {"participant_id": alice_num, "connected": True}

            # Grace key deleted in Redis
            assert not clean.exists(disconnect_grace_key(room_id, alice_pid))
            assert not clean.exists(disconnect_at_key(room_id, alice_pid))

            # Alice can chat normally
            say(alice_ws2, "I am back!")
            msg = wait_for(bob_ws, "game_message")
            assert msg["text"] == "I am back!"
            assert msg["participant_id"] == alice_num


def test_reconnect_after_grace_period_refuses_chat_messages(server, clean: redis.Redis):
    room_id, (alice_id, alice_token), (_, bob_token) = discussion_room(server)
    alice_label = my_label(server, alice_token, room_id)
    alice_num = label_number(alice_label)
    alice_pid = participant_id(room_id, alice_id)

    with room_socket(server, bob_token, room_id) as bob_ws:
        snapshot(bob_ws)

        with room_socket(server, alice_token, room_id) as alice_ws:
            snapshot(alice_ws)
            wait_for(bob_ws, "player_connection")

        # Alice disconnects
        wait_for(bob_ws, "player_connection")

        # Simulate 30s grace period expiration by removing the grace key while leaving disconnect_at
        clean.delete(disconnect_grace_key(room_id, alice_pid))
        clean.delete(disconnect_grace_key(room_id, alice_num))

        # Alice reconnects after grace period expired
        with room_socket(server, alice_token, room_id) as alice_ws2:
            snap = snapshot(alice_ws2)
            assert snap["room"]["id"] == room_id

            # Bob sees Alice reconnected
            rec_event = wait_for(bob_ws, "player_connection")
            assert rec_event == {"participant_id": alice_num, "connected": True}

            # Redis marked as expired
            assert clean.exists(disconnect_expired_key(room_id, alice_pid))

            # Alice tries to send a message
            say(alice_ws2, "Can you hear me?")
            err = next_frame(alice_ws2)
            assert err == {
                "type": "game_error",
                "payload": {"detail": "Grace period expired"},
            }

            # No message saved in database
            assert sql("SELECT count(*) FROM game_messages WHERE room_id = :r", r=room_id) == [(0,)]

            # Alice remains in room_participants (seat is never lost)
            assert sql("SELECT count(*) FROM game_participants WHERE room_id = :r", r=room_id) == [
                (2,)
            ]


def test_multiple_tabs_disconnect_only_when_last_socket_closes(server, clean: redis.Redis):
    room_id, (alice_id, alice_token), (_, bob_token) = discussion_room(server)
    alice_label = my_label(server, alice_token, room_id)
    alice_num = label_number(alice_label)
    alice_pid = participant_id(room_id, alice_id)

    with room_socket(server, bob_token, room_id) as bob_ws:
        snapshot(bob_ws)

        with (
            room_socket(server, alice_token, room_id) as alice_tab1,
            room_socket(server, alice_token, room_id) as alice_tab2,
        ):
            snapshot(alice_tab1)
            wait_for(bob_ws, "player_connection")
            snapshot(alice_tab2)

            # Tab 1 closes -> Bob does NOT receive connected: False because Tab 2 is alive
            alice_tab1.close()
            assert not clean.exists(disconnect_grace_key(room_id, alice_pid))

        # Tab 2 closes -> Now Bob receives connected: False
        disc_event = wait_for(bob_ws, "player_connection")
        assert disc_event == {"participant_id": alice_num, "connected": False}
        assert clean.exists(disconnect_grace_key(room_id, alice_pid))


def test_socket_closed_in_finished_or_closed_room_does_not_set_grace_period(
    server, clean: redis.Redis
):
    room_id, (alice_id, alice_token), _ = discussion_room(server)
    alice_pid = participant_id(room_id, alice_id)

    set_state(room_id, "finished", finished_at="now()")

    with room_socket(server, alice_token, room_id) as alice_ws:
        snapshot(alice_ws)

    assert not clean.exists(disconnect_grace_key(room_id, alice_pid))
    assert not clean.exists(disconnect_at_key(room_id, alice_pid))


def test_server_phase_timers_continue_during_disconnect(server):
    room_id, (_, alice_token), _ = discussion_room(server)

    room_before = get_room(server, alice_token, room_id)
    phase_ends_at = room_before["phase_ends_at"]
    assert phase_ends_at is not None

    with room_socket(server, alice_token, room_id) as alice_ws:
        snapshot(alice_ws)

    # Room phase end is intact on server; client disconnect cannot block or delay phase
    room_after = get_room(server, alice_token, room_id)
    assert room_after["phase_ends_at"] == phase_ends_at
    assert room_after["state"] == "discussion"

    # Room phase end is intact on server; client disconnect cannot block or delay phase
    room_after = get_room(server, alice_token, room_id)
    assert room_after["phase_ends_at"] == phase_ends_at
    assert room_after["state"] == "discussion"
