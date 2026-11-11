"""The WebSocket layer on a real server, a real database and a real Redis: tickets, the socket's
login check (close code 1008), ping / pong and events for a user on every socket and worker.

The server is uvicorn, started by the test on a free port (conftest.running_server), and the
client is a real WebSocket client, like the browser's. These tests use TEST_DATABASE_URL and
TEST_REDIS_URL only, and are skipped without them (conftest.py says how to start both). The users
are made up: added straight to the database, already verified, and logged in through the real
/api/auth/login.
"""

import asyncio
import json
import time
from collections.abc import Iterator

import httpx2
import pytest
import redis
import redis.asyncio
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
from app.realtime import service
from app.realtime.constants import TICKET_LIFETIME_SECONDS

pytestmark = [needs_database, needs_redis]

PASSWORD = "correct horse battery"
# Argon2 is slow on purpose, so the hash is made once and shared by every test user.
PASSWORD_HASH = security.hash_password(PASSWORD)

WAIT = 5  # seconds a test waits for a frame that must come
PONG = {"type": "pong", "payload": None}


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


def delete_ws_keys(client: redis.Redis) -> None:
    """Delete this layer's keys (their names start with "ws:"), and nothing else."""
    for key in client.scan_iter("ws:*"):
        client.delete(key)


@pytest.fixture
def redis_db() -> Iterator[redis.Redis]:
    """The test Redis, with no key of this layer before and after each test."""
    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    delete_ws_keys(client)
    yield client
    delete_ws_keys(client)
    client.close()


def new_app():
    """An app on the test database and the test Redis."""
    return build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)


@pytest.fixture
def server(redis_db) -> Iterator[str]:
    """One running API (like one API worker) with no users yet. Gives its address."""
    # CASCADE also empties friendships and every other table that points at users.
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    with running_server(new_app()) as address:
        yield address


def sign_in(server: str, email: str) -> tuple[int, str]:
    """A made-up verified account, logged in. Returns its id and its access token."""
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :password_hash, true) RETURNING id",
        email=email,
        password_hash=PASSWORD_HASH,
    )
    response = httpx2.post(
        f"http://{server}/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return user_id, response.json()["access_token"]


def ask_ticket(server: str, access_token: str | None = None):
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    return httpx2.post(f"http://{server}/api/ws/ticket", headers=headers)


def new_ticket(server: str, access_token: str) -> str:
    response = ask_ticket(server, access_token)
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


def open_socket(server: str, query: str) -> ClientConnection:
    """A WebSocket client on /ws<query>, e.g. query="?ticket=..."."""
    return connect(f"ws://{server}/ws{query}", open_timeout=WAIT)


def open_user_socket(server: str, access_token: str) -> ClientConnection:
    """What the frontend does: get a new ticket, then open /ws?ticket=<it>."""
    return open_socket(server, f"?ticket={new_ticket(server, access_token)}")


def ping(ws: ClientConnection) -> dict:
    """Send a ping; returns the next frame from the server."""
    ws.send(json.dumps({"type": "ping"}))
    return json.loads(ws.recv(timeout=WAIT))


def close_code(ws: ClientConnection) -> int:
    """Wait until the server closes the socket; returns the close code it sent."""
    with pytest.raises(ConnectionClosed):
        ws.recv(timeout=WAIT)
    return ws.close_code


def next_frame(ws: ClientConnection) -> dict:
    return json.loads(ws.recv(timeout=WAIT))


def nothing_arrives(ws: ClientConnection, seconds: float = 0.5) -> bool:
    """True when no frame comes within `seconds`."""
    try:
        ws.recv(timeout=seconds)
    except TimeoutError:
        return True
    return False


def wait_for_listeners(redis_db: redis.Redis, user_id: int, count: int) -> None:
    """Wait until `count` sockets listen on the user's channel: a new socket subscribes a
    moment after it opens, and an event published before that would not reach it."""
    deadline = time.monotonic() + WAIT
    while redis_db.pubsub_numsub(f"ws:user:{user_id}")[0][1] < count:
        assert time.monotonic() < deadline, "the sockets never listened"
        time.sleep(0.01)


def send_event(user_id: int, event_type: str, payload: object, redis_url: str = TEST_REDIS_URL):
    """What another card does after a change: call send_to_user(). Any process can, so this
    one runs outside both test servers."""

    async def send() -> None:
        client = redis.asyncio.Redis.from_url(redis_url, decode_responses=True)
        await service.send_to_user(client, user_id, event_type, payload)
        await client.aclose()

    asyncio.run(send())


# --- The ticket -------------------------------------------------------------------------------


def test_a_ticket_needs_a_logged_in_user(server):
    response = ask_ticket(server)
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "401", "detail": "Not authenticated"}}


def test_a_ticket_is_kept_in_redis_for_30_seconds_with_its_user(server, redis_db):
    user_id, token = sign_in(server, "ana@example.com")
    ticket = new_ticket(server, token)
    key = f"ws:ticket:{ticket}"
    assert json.loads(redis_db.get(key)) == {"user_id": user_id, "token_version": 1}
    assert 0 < redis_db.ttl(key) <= TICKET_LIFETIME_SECONDS
    assert new_ticket(server, token) != ticket  # every request gets a new one


# --- Opening the socket -----------------------------------------------------------------------


def test_a_good_ticket_opens_the_socket_and_ping_gets_pong(server):
    _, token = sign_in(server, "ana@example.com")
    with open_user_socket(server, token) as ws:
        assert ping(ws) == PONG
        assert ping(ws) == PONG  # as often as the client likes


@pytest.mark.parametrize("query", ["", "?ticket=", "?ticket=made-up-ticket"])
def test_no_ticket_or_a_made_up_one_is_closed_with_1008(server, query):
    with open_socket(server, query) as ws:
        assert close_code(ws) == 1008
        assert ws.close_reason == "Invalid or expired ticket"


def test_a_ticket_opens_only_one_socket(server, redis_db):
    _, token = sign_in(server, "ana@example.com")
    ticket = new_ticket(server, token)
    with open_socket(server, f"?ticket={ticket}") as ws:
        assert ping(ws) == PONG
        with open_socket(server, f"?ticket={ticket}") as again:
            assert close_code(again) == 1008
    assert not redis_db.exists(f"ws:ticket:{ticket}")  # used up: gone from Redis


def test_an_expired_ticket_is_closed_with_1008(server, monkeypatch):
    monkeypatch.setattr(service, "TICKET_LIFETIME_SECONDS", 1)  # 1 s instead of 30
    _, token = sign_in(server, "ana@example.com")
    ticket = new_ticket(server, token)
    time.sleep(1.5)  # Redis deletes the ticket by itself after 1 s
    with open_socket(server, f"?ticket={ticket}") as ws:
        assert close_code(ws) == 1008


def test_a_deleted_user_is_closed_with_1008(server):
    user_id, token = sign_in(server, "ana@example.com")
    ticket = new_ticket(server, token)
    sql("UPDATE users SET status = 'deleted' WHERE id = :id", id=user_id)
    with open_socket(server, f"?ticket={ticket}") as ws:
        assert close_code(ws) == 1008


def test_a_password_change_after_the_ticket_is_closed_with_1008(server):
    user_id, token = sign_in(server, "ana@example.com")
    ticket = new_ticket(server, token)
    # A password change or reset (BE-04) raises token_version; the ticket kept the old one.
    sql("UPDATE users SET token_version = token_version + 1 WHERE id = :id", id=user_id)
    with open_socket(server, f"?ticket={ticket}") as ws:
        assert close_code(ws) == 1008


def test_frames_the_layer_does_not_know_are_ignored(server):
    _, token = sign_in(server, "ana@example.com")
    with open_user_socket(server, token) as ws:
        ws.send("not json")
        ws.send(b"\x00 a binary frame")
        ws.send(json.dumps(["ping"]))
        ws.send(json.dumps({"type": "something_new"}))
        assert ping(ws) == PONG  # the socket is still open, and nothing else came first


# --- Events for a user ------------------------------------------------------------------------


def test_an_event_reaches_every_socket_of_the_user_and_nobody_else(server, redis_db):
    ana_id, ana = sign_in(server, "ana@example.com")
    _, ben = sign_in(server, "ben@example.com")
    with (
        open_user_socket(server, ana) as ana_tab_1,
        open_user_socket(server, ana) as ana_tab_2,
        open_user_socket(server, ben) as ben_tab,
    ):
        wait_for_listeners(redis_db, ana_id, 2)
        send_event(ana_id, "something_happened", {"n": 1})
        # Every frame is {type, payload}.
        expected = {"type": "something_happened", "payload": {"n": 1}}
        assert next_frame(ana_tab_1) == expected
        assert next_frame(ana_tab_2) == expected
        assert nothing_arrives(ben_tab)


def test_an_event_reaches_the_user_on_every_api_worker(server, redis_db):
    ana_id, ana = sign_in(server, "ana@example.com")
    # A second API on the same database and Redis, like a second worker behind the proxy.
    with running_server(new_app()) as second_server:
        # A ticket from one worker opens a socket on the other: tickets live in Redis.
        ticket = new_ticket(server, ana)
        with (
            open_socket(second_server, f"?ticket={ticket}") as on_second,
            open_user_socket(server, ana) as on_first,
        ):
            wait_for_listeners(redis_db, ana_id, 2)
            send_event(ana_id, "something_happened", {"n": 2})
            expected = {"type": "something_happened", "payload": {"n": 2}}
            assert next_frame(on_first) == expected
            assert next_frame(on_second) == expected


def test_send_to_user_does_not_fail_when_redis_is_down():
    # Nothing listens on port 1: the event is lost and logged, and the caller goes on.
    send_event(1, "something_happened", None, redis_url="redis://127.0.0.1:1/0")


def test_a_socket_that_loses_its_redis_connection_is_closed_with_1011(server, redis_db):
    ana_id, ana = sign_in(server, "ana@example.com")
    with open_user_socket(server, ana) as ws:
        wait_for_listeners(redis_db, ana_id, 1)
        redis_db.client_kill_filter(_type="pubsub")  # cut every listening connection
        # It would get no more events: the server closes it, and the client reconnects.
        assert close_code(ws) == 1011
