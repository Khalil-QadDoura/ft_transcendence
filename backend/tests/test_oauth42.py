"""Login with 42 (BE-11) on a real database and a real Redis, against a fake 42.

The fake 42 is a small HTTP server started on this machine for each test: it answers the two
calls our server makes to 42 (the code for a token, then /v2/me), so no test ever contacts
the real 42 intra. Every user and key here is made up.
"""

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx2
import pytest
import redis
from conftest import (
    TEST_DATABASE_URL,
    TEST_REDIS_URL,
    alembic,
    build_app,
    free_port,
    needs_database,
    needs_redis,
    sql,
)
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import oauth42, security

pytestmark = [needs_database, needs_redis]

# Made-up keys of a made-up 42 app.
CLIENT_ID = "test-42-client-id"
CLIENT_SECRET = "test-42-client-secret"
EMAIL = "amina@student.42abudhabi.ae"
CALLBACK = "/api/auth/oauth/42/callback"
STATE_KEYS = "oauth42:state:*"


class Fake42:
    """What the fake 42 answers, and what it was asked. A test changes the answers."""

    def __init__(self):
        self.profile = {"id": 4242, "login": "amina", "email": EMAIL, "first_name": "Amina"}
        self.profile["last_name"] = "Test"
        self.token_status = 200
        self.token_body = None  # None: a normal answer with an access token
        self.me_status = 200
        self.me_body = None  # None: self.profile as JSON
        self.delay = 0.0  # seconds before each answer
        self.token_requests = []  # the form of each POST /oauth/token
        self.me_requests = []  # the Authorization header of each GET /v2/me


class Fake42Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (the name http.server looks for)
        fake = self.server.fake
        length = int(self.headers.get("Content-Length", 0))
        form = dict(parse_qsl(self.rfile.read(length).decode()))
        fake.token_requests.append(form)
        body = fake.token_body
        if body is None:
            body = json.dumps({"access_token": f"ft-token-for-{form.get('code')}"})
        self.answer(fake.token_status, body)

    def do_GET(self):  # noqa: N802
        fake = self.server.fake
        fake.me_requests.append(self.headers.get("Authorization"))
        body = fake.me_body if fake.me_body is not None else json.dumps(fake.profile)
        self.answer(fake.me_status, body)

    def answer(self, status: int, body: str) -> None:
        time.sleep(self.server.fake.delay)
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # keep the test output quiet
        pass


@pytest.fixture
def fake42() -> Iterator[Fake42]:
    """A fake 42 on a free local port, for one test."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake42Handler)
    server.fake = Fake42()
    server.fake.base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.fake
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


@pytest.fixture
def redis_db() -> Iterator[redis.Redis]:
    """The test Redis, without this file's keys (names starting with "oauth42:state:")."""
    with redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True) as client:
        for key in client.scan_iter(STATE_KEYS):
            client.delete(key)
        yield client
        for key in client.scan_iter(STATE_KEYS):
            client.delete(key)


def app_for(fake: Fake42, **overrides):
    """An app on the test database whose 42 is the fake one, with the made-up keys."""
    settings = {
        "database_url": TEST_DATABASE_URL,
        "ft_client_id": CLIENT_ID,
        "ft_client_secret": CLIENT_SECRET,
        "ft_authorize_url": f"{fake.base}/oauth/authorize",
        "ft_token_url": f"{fake.base}/oauth/token",
        "ft_me_url": f"{fake.base}/v2/me",
        **overrides,
    }
    return build_app(**settings)


def browser(app) -> TestClient:
    """A client that behaves like a browser on https://: it keeps cookies and sends the
    "Secure" ones back. It does not follow redirects, so a test can read each one."""
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


@pytest.fixture
def client(fake42, redis_db):
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    with browser(app_for(fake42)) as test_client:
        yield test_client


def start(client) -> str:
    """Press "Log in with 42". Returns the state from the address of 42's page."""
    response = client.get("/api/auth/oauth/42/start")
    assert response.status_code == 302, response.text
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


def callback(client, **params):
    """42 sends the browser back to us with these query parameters."""
    return client.get(CALLBACK, params=params)


def handed_to_frontend(response) -> dict:
    """Where the callback sends the browser: always the frontend's /oauth/callback page, with
    no query string. Returns what is after "#"."""
    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    assert (location.scheme, location.netloc, location.path) == (
        "https",
        "localhost",
        "/oauth/callback",
    )
    assert location.query == ""  # nothing after "?": the tokens never go there
    return dict(parse_qsl(location.fragment))


def login_with_42(client, code: str = "code-1") -> dict:
    """The whole login: the button, 42 (fake), the callback. Returns what the page gets."""
    state = start(client)
    return handed_to_frontend(callback(client, code=code, state=state))


def me(client, access_token: str):
    return client.get("/api/users/me", headers={"Authorization": f"Bearer {access_token}"})


def add_user(email=EMAIL, password="their password", verified=True, status="active") -> int:
    """An account made the usual way (with a password), straight in the database."""
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified, status)"
        " VALUES (:email, :hash, :verified, :status) RETURNING id",
        email=email,
        hash=security.hash_password(password),
        verified=verified,
        status=status,
    )
    return user_id


def password_login(client, password: str, email: str = EMAIL):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# The button: /start


def test_start_sends_the_browser_to_42_with_a_state_kept_in_redis(client, fake42, redis_db):
    response = client.get("/api/auth/oauth/42/start")

    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert (
        f"{location.scheme}://{location.netloc}{location.path}" == f"{fake42.base}/oauth/authorize"
    )
    query = {name: values[0] for name, values in parse_qs(location.query).items()}
    state = query.pop("state")
    assert query == {
        "client_id": CLIENT_ID,
        "redirect_uri": "https://localhost/api/auth/oauth/42/callback",
        "response_type": "code",
        "scope": "public",
    }
    assert len(state) == 43  # 32 random bytes, URL-safe
    assert CLIENT_SECRET not in response.headers["location"]  # the secret never goes there
    # Redis keeps it for 10 minutes at most.
    assert 0 < redis_db.ttl(f"oauth42:state:{state}") <= 600
    # And this browser keeps it in a cookie that only the callback gets back.
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"oauth42_state={state};")
    for part in ("HttpOnly", "Max-Age=600", f"Path={CALLBACK}", "SameSite=lax", "Secure"):
        assert part in cookie


def test_each_start_gets_its_own_state(client, redis_db):
    states = {start(client) for _ in range(3)}
    assert len(states) == 3
    assert len(list(redis_db.scan_iter(STATE_KEYS))) == 3


@pytest.mark.parametrize(
    "keys",
    [{}, {"ft_client_id": CLIENT_ID}, {"ft_client_secret": CLIENT_SECRET}],
    ids=["no keys", "no secret", "no client id"],
)
def test_start_without_the_42_keys_is_a_clear_503(fake42, redis_db, keys):
    app = app_for(fake42, **{"ft_client_id": "", "ft_client_secret": "", **keys})
    with browser(app) as client:
        response = client.get("/api/auth/oauth/42/start")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "503", "detail": "Login with 42 is not set up on this server"}
    }
    assert "location" not in response.headers
    assert list(redis_db.scan_iter(STATE_KEYS)) == []


def test_start_allows_10_requests_a_minute_per_ip(client):
    for _ in range(10):
        start(client)
    response = client.get("/api/auth/oauth/42/start")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "429"


# The callback: a new account, an existing one


def test_a_new_42_user_gets_a_verified_account_and_our_tokens(client, fake42, redis_db):
    state = start(client)
    response = callback(client, code="code-1", state=state)

    tokens = handed_to_frontend(response)
    assert set(tokens) == {"access_token", "refresh_token", "token_type"}
    assert tokens["token_type"] == "bearer"
    assert response.headers["cache-control"] == "no-store"
    # The account: verified (42 checked the email), no password, the names from 42.
    assert sql(
        "SELECT id, email, is_email_verified, password_hash, first_name, last_name FROM users"
    ) == [(1, EMAIL, True, None, "Amina", "Test")]
    # Our tokens work like the ones of a password login.
    profile = me(client, tokens["access_token"])
    assert profile.status_code == 200
    assert (profile.json()["id"], profile.json()["email"]) == (1, EMAIL)
    refreshed = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    # Our server asked 42 for a token with our keys and the code, then for the profile.
    assert fake42.token_requests == [
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": "code-1",
            "redirect_uri": "https://localhost/api/auth/oauth/42/callback",
        }
    ]
    assert fake42.me_requests == ["Bearer ft-token-for-code-1"]
    # The state is used up, and the browser is told to forget its cookie.
    assert redis_db.exists(f"oauth42:state:{state}") == 0
    assert 'oauth42_state=""' in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_logging_in_with_42_again_uses_the_same_account(client):
    first = login_with_42(client, code="code-1")
    second = login_with_42(client, code="code-2")
    assert me(client, first["access_token"]).json()["id"] == 1
    assert me(client, second["access_token"]).json()["id"] == 1
    assert sql("SELECT count(*) FROM users") == [(1,)]
    assert sql("SELECT count(*) FROM refresh_tokens") == [(2,)]


def test_long_names_from_42_are_cut_to_fit_the_profile(client, fake42):
    fake42.profile.update(first_name="  " + "A" * 60, last_name="   ")
    login_with_42(client)
    assert sql("SELECT first_name, last_name FROM users") == [("A" * 50, None)]


def test_an_existing_account_with_that_email_is_linked_and_keeps_its_password(client, fake42):
    user_id = add_user()
    fake42.profile["email"] = EMAIL.upper()  # emails are compared in lower case

    tokens = login_with_42(client)

    assert me(client, tokens["access_token"]).json()["id"] == user_id
    assert sql("SELECT count(*) FROM users") == [(1,)]
    assert sql("SELECT is_email_verified, token_version FROM users") == [(True, 1)]
    assert password_login(client, "their password").status_code == 200


def test_an_unverified_account_becomes_verified_and_loses_the_unproven_password(client):
    # Someone signed up with this email and never opened the verification link: maybe not
    # its owner. The 42 login proves who owns the email, so the account becomes theirs.
    user_id = add_user(password="someone else's password", verified=False)

    tokens = login_with_42(client)

    assert me(client, tokens["access_token"]).json()["id"] == user_id
    assert sql("SELECT is_email_verified, password_hash, token_version FROM users") == [
        (True, None, 2)
    ]
    assert password_login(client, "someone else's password").status_code == 401


def test_a_deleted_account_cannot_log_in_with_42(client, fake42):
    add_user(status="deleted")

    assert login_with_42(client) == {"error": "account_disabled"}
    assert sql("SELECT status, is_email_verified FROM users") == [("deleted", True)]
    assert sql("SELECT count(*) FROM refresh_tokens") == [(0,)]


# The callback: the state


def test_a_callback_without_a_state_is_refused(client, fake42):
    start(client)
    assert handed_to_frontend(callback(client, code="code-1")) == {"error": "invalid_state"}
    assert fake42.token_requests == []


def test_a_state_that_is_not_this_browsers_is_refused_and_stays_usable(fake42, client):
    # Someone presses the button in their own browser and sends the callback link to another
    # browser (login CSRF): that browser has no matching cookie, so it is refused there.
    state = start(client)
    with browser(app_for(fake42)) as other_browser:
        response = callback(other_browser, code="code-1", state=state)
    assert handed_to_frontend(response) == {"error": "invalid_state"}
    assert fake42.token_requests == []
    # The browser that pressed the button can still finish.
    assert "access_token" in handed_to_frontend(callback(client, code="code-1", state=state))


def test_a_state_we_never_handed_out_is_refused(client, fake42):
    start(client)
    made_up = security.new_oauth_state()
    response = client.get(
        CALLBACK,
        params={"code": "code-1", "state": made_up},
        headers={"Cookie": f"oauth42_state={made_up}"},  # even with a matching cookie
    )
    assert handed_to_frontend(response) == {"error": "invalid_state"}
    assert fake42.token_requests == []


def test_an_expired_state_is_refused(client, fake42, redis_db):
    state = start(client)
    redis_db.pexpire(f"oauth42:state:{state}", 1)  # its 10 minutes are over
    time.sleep(0.05)
    assert handed_to_frontend(callback(client, code="code-1", state=state)) == {
        "error": "invalid_state"
    }
    assert fake42.token_requests == []


def test_a_used_state_is_refused(client, fake42):
    state = start(client)
    assert "access_token" in handed_to_frontend(callback(client, code="code-1", state=state))
    # The same callback again (a reload, or a copied link): refused, and 42 is not asked.
    response = client.get(
        CALLBACK,
        params={"code": "code-1", "state": state},
        headers={"Cookie": f"oauth42_state={state}"},
    )
    assert handed_to_frontend(response) == {"error": "invalid_state"}
    assert len(fake42.token_requests) == 1


# The callback: what 42 sends back


@pytest.mark.parametrize(
    ("error", "reason"),
    [("access_denied", "access_denied"), ("server_error", "ft_unavailable")],
)
def test_an_error_from_42_is_passed_on_and_uses_up_the_state(
    client, fake42, redis_db, error, reason
):
    state = start(client)
    response = callback(client, state=state, error=error, error_description="Some text")
    assert handed_to_frontend(response) == {"error": reason}
    assert redis_db.exists(f"oauth42:state:{state}") == 0
    assert fake42.token_requests == []


def test_a_callback_with_a_state_but_no_code_is_refused(client, fake42):
    state = start(client)
    assert handed_to_frontend(callback(client, state=state)) == {"error": "invalid_request"}
    assert fake42.token_requests == []


@pytest.mark.parametrize(
    "failure",
    [
        "token refused",
        "token answer without a token",
        "token answer not json",
        "profile refused",
        "profile not json",
        "profile not an object",
        "42 too slow",
        "42 unreachable",
    ],
)
def test_a_failure_at_42_ends_on_the_frontend_page_not_in_a_500(
    fake42, redis_db, monkeypatch, failure
):
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    overrides = {}
    if failure == "token refused":
        fake42.token_status, fake42.token_body = 401, '{"error": "invalid_grant"}'
    elif failure == "token answer without a token":
        fake42.token_body = '{"token_type": "bearer"}'
    elif failure == "token answer not json":
        fake42.token_body = "<html>Bad gateway</html>"
    elif failure == "profile refused":
        fake42.me_status = 500
    elif failure == "profile not json":
        fake42.me_body = "<html>Maintenance</html>"
    elif failure == "profile not an object":
        fake42.me_body = '["a", "list"]'
    elif failure == "42 too slow":
        monkeypatch.setattr(oauth42, "FT_REQUEST_TIMEOUT_SEC", 0.2)
        fake42.delay = 1.0
    else:  # nothing listens on this port
        overrides["ft_token_url"] = f"http://127.0.0.1:{free_port()}/oauth/token"

    with browser(app_for(fake42, **overrides)) as client:
        state = start(client)
        response = callback(client, code="code-1", state=state)

    assert handed_to_frontend(response) == {"error": "ft_unavailable"}
    assert sql("SELECT count(*) FROM users") == [(0,)]


@pytest.mark.parametrize(
    "email",
    ["no email field", None, "", "not-an-email", 42],
)
def test_a_42_profile_without_a_valid_email_cannot_log_in(client, fake42, email):
    if email == "no email field":
        del fake42.profile["email"]
    else:
        fake42.profile["email"] = email
    assert login_with_42(client) == {"error": "no_email"}
    assert sql("SELECT count(*) FROM users") == [(0,)]


# At the same moment


async def wait_until_waiting_for_a_lock(engine, count: int) -> None:
    """Wait (10 seconds at most) until `count` database sessions are waiting for a lock."""
    for _ in range(200):
        async with engine.connect() as watcher:
            waiting = await watcher.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
        if waiting == count:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{count} request(s) should be waiting for a lock, not {waiting}")


def https_client(app) -> httpx2.AsyncClient:
    """Like browser(), for requests sent at the same moment from one event loop."""
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="https://testserver"
    )


def test_two_callbacks_with_the_same_state_only_one_wins(fake42, redis_db):
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    fake42.delay = 0.2  # 42 is slow, so both callbacks are on their way at once

    async def race() -> list[dict]:
        app = app_for(fake42)
        async with https_client(app) as http:
            state = parse_qs(
                urlsplit((await http.get("/api/auth/oauth/42/start")).headers["location"]).query
            )["state"][0]
            answers = await asyncio.gather(
                *(http.get(CALLBACK, params={"code": "code-1", "state": state}) for _ in "ab")
            )
        await app.state.engine.dispose()
        return [handed_to_frontend(answer) for answer in answers]

    results = asyncio.run(race())

    assert sorted("access_token" in result for result in results) == [False, True]
    assert {"error": "invalid_state"} in results
    assert len(fake42.token_requests) == 1  # the loser never reached 42
    assert sql("SELECT count(*) FROM users") == [(1,)]


def test_two_42_logins_creating_the_same_new_account_make_one_account(fake42, redis_db):
    # Two tabs finish a 42 login for the same new email at the same moment. A gate inserts
    # that email without saving it, so both logins find no account, both try to create it,
    # and both wait on the gate. The gate then gives up, and they go on one after the other.
    sql("TRUNCATE users RESTART IDENTITY CASCADE")

    async def race() -> list[dict]:
        app = app_for(fake42)
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with (
            https_client(app) as tab_a,
            https_client(app) as tab_b,
            engine.connect() as gate,
        ):
            states = []
            for tab in (tab_a, tab_b):
                location = (await tab.get("/api/auth/oauth/42/start")).headers["location"]
                states.append(parse_qs(urlsplit(location).query)["state"][0])
            await gate.execute(text("INSERT INTO users (email) VALUES (:email)"), {"email": EMAIL})
            tasks = [
                asyncio.create_task(tab.get(CALLBACK, params={"code": "c", "state": state}))
                for tab, state in zip((tab_a, tab_b), states, strict=True)
            ]
            await wait_until_waiting_for_a_lock(engine, 2)
            await gate.rollback()
            ids = []
            for task, tab in zip(tasks, (tab_a, tab_b), strict=True):
                tokens = handed_to_frontend(await task)
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}
                ids.append((await tab.get("/api/users/me", headers=headers)).json()["id"])
        await app.state.engine.dispose()
        await engine.dispose()
        return ids

    ids = asyncio.run(race())

    assert sql("SELECT email, is_email_verified FROM users") == [(EMAIL, True)]
    [(user_id,)] = sql("SELECT id FROM users")
    assert ids == [user_id, user_id]  # both tabs are logged in to the one account


@pytest.mark.parametrize("first", ["42 login", "sign-up"])
def test_a_42_login_and_a_sign_up_at_the_same_moment_never_leave_a_password(fake42, first):
    # An unverified account; someone signs up again with this email (a new password) at the
    # moment its owner logs in with 42. Whichever goes first, the owner ends up with a
    # verified account that no password opens (the sign-up gets 409 when it comes second).
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    add_user(password="first password", verified=False)

    async def race() -> dict:
        app = app_for(fake42)
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with https_client(app) as http, engine.connect() as gate:
            location = (await http.get("/api/auth/oauth/42/start")).headers["location"]
            state = parse_qs(urlsplit(location).query)["state"][0]
            requests = {
                "42 login": lambda: http.get(CALLBACK, params={"code": "c", "state": state}),
                "sign-up": lambda: http.post(
                    "/api/auth/register", json={"email": EMAIL, "password": "second password"}
                ),
            }
            # The gate holds the account's row locked, so both requests wait there, in order.
            await gate.execute(text("SELECT id FROM users FOR UPDATE"))
            tasks = {}
            for name in (first, *(other for other in requests if other != first)):
                tasks[name] = asyncio.create_task(requests[name]())
                await wait_until_waiting_for_a_lock(engine, len(tasks))
            await gate.commit()
            answers = {name: await task for name, task in tasks.items()}
        await app.state.engine.dispose()
        await engine.dispose()
        return answers

    answers = asyncio.run(race())

    assert "access_token" in handed_to_frontend(answers["42 login"])
    assert answers["sign-up"].status_code == (409 if first == "42 login" else 202)
    assert sql("SELECT is_email_verified, password_hash FROM users") == [(True, None)]


@pytest.mark.parametrize("first", ["42 login", "deletion"])
def test_a_42_login_and_a_deletion_at_the_same_moment_end_with_no_working_token(fake42, first):
    # The owner deletes the account in one tab while a 42 login finishes in another. If the
    # deletion goes first, the 42 login is refused; if the 42 login goes first, its new tokens
    # die with the deletion. Either way nobody is logged in to a deleted account.
    sql("TRUNCATE users RESTART IDENTITY CASCADE")

    async def race() -> tuple[dict, str | None]:
        app = app_for(fake42)
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with https_client(app) as http, engine.connect() as gate:
            # Logged in once already (with 42), so the account can be deleted.
            location = (await http.get("/api/auth/oauth/42/start")).headers["location"]
            state = parse_qs(urlsplit(location).query)["state"][0]
            answer = await http.get(CALLBACK, params={"code": "c1", "state": state})
            old_access = handed_to_frontend(answer)["access_token"]
            location = (await http.get("/api/auth/oauth/42/start")).headers["location"]
            state = parse_qs(urlsplit(location).query)["state"][0]
            bearer = {"Authorization": f"Bearer {old_access}"}
            requests = {
                "42 login": lambda: http.get(CALLBACK, params={"code": "c2", "state": state}),
                "deletion": lambda: http.delete("/api/users/me", headers=bearer),
            }
            await gate.execute(text("SELECT id FROM users FOR UPDATE"))
            tasks = {}
            for name in (first, *(other for other in requests if other != first)):
                tasks[name] = asyncio.create_task(requests[name]())
                await wait_until_waiting_for_a_lock(engine, len(tasks))
            await gate.commit()
            answers = {name: await task for name, task in tasks.items()}
            result = handed_to_frontend(answers["42 login"])
            assert answers["deletion"].status_code == 204
            new_access = result.get("access_token")
            still_works = None
            if new_access:
                headers = {"Authorization": f"Bearer {new_access}"}
                still_works = (await http.get("/api/users/me", headers=headers)).status_code
        await app.state.engine.dispose()
        await engine.dispose()
        return result, still_works

    result, me_status = asyncio.run(race())

    assert sql("SELECT status FROM users") == [("deleted",)]
    if first == "deletion":
        assert result == {"error": "account_disabled"}
    else:
        assert "access_token" in result
        assert me_status == 401  # the tokens stopped working with the deletion
