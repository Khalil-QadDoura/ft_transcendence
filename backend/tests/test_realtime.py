"""The WebSocket layer on a real server, a real database and a real Redis: tickets, the socket's
login check (close code 1008), ping / pong, events for a user on every socket and worker, and
presence for friends.

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
from app.realtime.constants import PRESENCE_TTL_SECONDS, TICKET_LIFETIME_SECONDS

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


def with_redis(work, redis_url: str = TEST_REDIS_URL):
    """Run `work(client)` with an async Redis client, as code inside an API process does. Any
    process can, so this runs outside the test servers."""

    async def run():
        client = redis.asyncio.Redis.from_url(redis_url, decode_responses=True)
        try:
            return await work(client)
        finally:
            await client.aclose()

    return asyncio.run(run())


def send_event(user_id: int, event_type: str, payload: object, redis_url: str = TEST_REDIS_URL):
    """What another card does after a change: call send_to_user()."""
    with_redis(lambda client: service.send_to_user(client, user_id, event_type, payload), redis_url)


def online(user_id: int) -> bool:
    """What the friends list (BE-22) will ask: service.is_online()."""
    return with_redis(lambda client: service.is_online(client, user_id))


def make_friends(requester_id: int, addressee_id: int, status: str = "accepted") -> None:
    """A friendship row, as the friends endpoints (BE-22) will write it."""
    sql(
        "INSERT INTO friendships (requester_id, addressee_id, status)"
        " VALUES (:requester_id, :addressee_id, :status)",
        requester_id=requester_id,
        addressee_id=addressee_id,
        status=status,
    )


def presence(user_id: int, is_online: bool) -> dict:
    return {"type": "presence", "payload": {"user_id": user_id, "is_online": is_online}}


# --- The ticket -------------------------------------------------------------------------------


def test_a_ticket_needs_a_logged_in_user(server):
    response = ask_ticket(server)
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "401", "detail": "Not authenticated"}}


def test_a_ticket_is_kept_in_redis_with_its_user_until_it_expires(server, redis_db):
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


# --- Presence ---------------------------------------------------------------------------------


def test_friends_hear_when_the_first_socket_opens_and_the_last_one_closes(server, redis_db):
    ana_id, ana = sign_in(server, "ana@example.com")
    ben_id, ben = sign_in(server, "ben@example.com")
    make_friends(ana_id, ben_id)  # Ana asked, Ben accepted
    with open_user_socket(server, ben) as ben_tab:
        wait_for_listeners(redis_db, ben_id, 1)
        with open_user_socket(server, ana):
            assert next_frame(ben_tab) == presence(ana_id, True)
            with open_user_socket(server, ana) as ana_tab_2:
                assert ping(ana_tab_2) == PONG  # a second tab; Ana was online already
                assert nothing_arrives(ben_tab)
            assert nothing_arrives(ben_tab)  # the first tab is still open: still online
        assert next_frame(ben_tab) == presence(ana_id, False)  # the last tab closed


def test_presence_reaches_a_friend_on_another_api_worker(server, redis_db):
    ana_id, ana = sign_in(server, "ana@example.com")
    ben_id, ben = sign_in(server, "ben@example.com")
    make_friends(ana_id, ben_id)  # Ana asked: here Ben is the one who accepted
    with running_server(new_app()) as second_server, open_user_socket(server, ana) as ana_tab:
        wait_for_listeners(redis_db, ana_id, 1)
        with open_user_socket(second_server, ben):
            assert next_frame(ana_tab) == presence(ben_id, True)
        assert next_frame(ana_tab) == presence(ben_id, False)


def test_no_presence_for_strangers_or_requests_not_accepted(server, redis_db):
    ana_id, ana = sign_in(server, "ana@example.com")
    cleo_id, cleo = sign_in(server, "cleo@example.com")  # no friendship at all
    dan_id, dan = sign_in(server, "dan@example.com")
    eve_id, eve = sign_in(server, "eve@example.com")
    make_friends(dan_id, ana_id, status="pending")  # Dan asked; Ana has not answered
    make_friends(eve_id, ana_id, status="declined")
    with (
        open_user_socket(server, cleo) as cleo_tab,
        open_user_socket(server, dan) as dan_tab,
        open_user_socket(server, eve) as eve_tab,
    ):
        for user_id in (cleo_id, dan_id, eve_id):
            wait_for_listeners(redis_db, user_id, 1)
        with open_user_socket(server, ana) as ana_tab:
            assert ping(ana_tab) == PONG  # Ana's socket is open and counted
            assert online(ana_id)
            assert nothing_arrives(cleo_tab)
            assert nothing_arrives(dan_tab)
            assert nothing_arrives(eve_tab)


def test_presence_is_a_key_in_redis_with_a_ttl(server, redis_db):
    ana_id, ana = sign_in(server, "ana@example.com")
    key = f"ws:presence:{ana_id}"
    assert not online(ana_id)
    with open_user_socket(server, ana) as ws:
        assert ping(ws) == PONG
        assert online(ana_id)
        assert redis_db.zcard(key) == 1  # one open socket
        assert 0 < redis_db.ttl(key) <= PRESENCE_TTL_SECONDS
    deadline = time.monotonic() + WAIT
    while redis_db.exists(key):  # the server cleans up just after the socket closes
        assert time.monotonic() < deadline, "the presence key was never removed"
        time.sleep(0.01)
    assert not online(ana_id)


def test_without_pings_the_user_stops_counting_as_online(server, redis_db, monkeypatch):
    monkeypatch.setattr(service, "PRESENCE_TTL_SECONDS", 1)  # 1 s instead of 60
    ana_id, ana = sign_in(server, "ana@example.com")
    with open_user_socket(server, ana) as ws:
        for _ in range(4):  # a ping every 0.5 s keeps Ana online past the 1 s limit
            time.sleep(0.5)
            assert ping(ws) == PONG
        assert online(ana_id)
        # No ping for longer than the limit, as when an API process crashes: Ana stops
        # counting as online, and Redis deletes the key by itself.
        time.sleep(1.5)
        assert not online(ana_id)
        assert not redis_db.exists(f"ws:presence:{ana_id}")
