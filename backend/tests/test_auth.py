"""Sign-up and login on a real database: register, email, verify, login, refresh, logout.

Each test starts with an empty users table, so these tests use TEST_DATABASE_URL only and are
skipped without it (conftest.py says how to start one). Emails go to a fake mailer.
"""

import asyncio
import re
from datetime import timedelta

import httpx2
import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import security
from app.auth.deps import CurrentUser
from app.core.mailer import get_mailer

pytestmark = needs_database

PASSWORD = "correct horse battery"

# A test-only route behind the login check, standing in for /users/me (BE-05).
protected = APIRouter()


@protected.get("/api/test/whoami")
async def who_am_i_route(user: CurrentUser):
    return {"id": user.id, "email": user.email}


class FakeMailer:
    """Stands in for the real mailer: keeps each email instead of sending it."""

    def __init__(self):
        self.sent = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


@pytest.fixture
def mailbox():
    return FakeMailer()


@pytest.fixture
def client(mailbox):
    """This file's client: an app on the test database, with no users yet and a fake mailer."""
    # CASCADE also empties refresh_tokens and every other table that points at users.
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    app = build_app(database_url=TEST_DATABASE_URL)
    app.dependency_overrides[get_mailer] = lambda: mailbox
    app.include_router(protected)
    with TestClient(app) as test_client:
        yield test_client


def register(client, email="ana@example.com", password=PASSWORD):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def link_token(email: dict) -> str:
    """The token of the email's link, which must open the frontend's /verify-email page."""
    match = re.search(r"https://localhost/verify-email\?token=(\S+)", email["body"])
    assert match, email["body"]
    return match.group(1)


def verify(client, token: str):
    return client.get("/api/auth/verify", params={"token": token})


def sign_up(client, mailbox, email="ana@example.com", password=PASSWORD) -> None:
    """Register, then open the link of the email: a verified account, ready to log in."""
    assert register(client, email, password).status_code == 202
    assert verify(client, link_token(mailbox.sent[-1])).status_code == 200


def login(client, email="ana@example.com", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def refresh(client, refresh_token: str):
    return client.post("/api/auth/refresh", json={"refresh_token": refresh_token})


def logout(client, refresh_token: str):
    return client.post("/api/auth/logout", json={"refresh_token": refresh_token})


def who_am_i(client, access_token: str | None):
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    return client.get("/api/test/whoami", headers=headers)


def claims(client, token: str, scope: str) -> dict:
    """What a token says inside (checked with the app's secret)."""
    return security.read_token(client.app.state.settings.jwt_secret, token, scope)


def test_the_whole_journey(client, mailbox):
    # 1. Register: one user, not verified yet, and one email with the link.
    assert register(client, email="Ana@Example.com").status_code == 202
    assert sql("SELECT email, is_email_verified FROM users") == [("ana@example.com", False)]
    [email] = mailbox.sent
    # 2. The link opens the frontend's page, which calls verify with the token.
    assert verify(client, link_token(email)).json()["verified"] is True
    assert sql("SELECT is_email_verified FROM users") == [(True,)]
    # 3. Login: a token pair; the refresh token is stored by its id.
    first = login(client).json()
    assert sql("SELECT count(*) FROM refresh_tokens WHERE NOT revoked") == [(1,)]
    # 4. The access token opens protected routes.
    response = who_am_i(client, first["access_token"])
    assert response.json() == {"id": 1, "email": "ana@example.com"}
    # 5. Refresh: a new pair; the old refresh token is used up.
    second = refresh(client, first["refresh_token"]).json()
    assert who_am_i(client, second["access_token"]).status_code == 200
    assert refresh(client, first["refresh_token"]).status_code == 401
    # 6. Logout: the refresh token stops working. (The access token still works until it
    #    expires, at most 15 minutes; the frontend forgets it.)
    assert logout(client, second["refresh_token"]).status_code == 204
    assert refresh(client, second["refresh_token"]).status_code == 401
    assert sql("SELECT revoked FROM refresh_tokens ORDER BY id") == [(True,), (True,)]


def test_register_answers_202_and_emails_a_link_to_the_frontend(client, mailbox):
    response = register(client)
    assert response.status_code == 202
    assert response.json() == {"message": "Check your email for the verification link"}

    [email] = mailbox.sent
    assert email["to"] == "ana@example.com"
    assert email["subject"] == "Verify your WOZU account"
    assert link_token(email)
    assert sql("SELECT email, is_email_verified FROM users") == [("ana@example.com", False)]


def test_stored_password_is_an_argon2id_hash_never_the_plain_text(client):
    register(client)
    [(password_hash,)] = sql("SELECT password_hash FROM users")
    assert password_hash.startswith("$argon2id$")
    assert PASSWORD not in password_hash
    assert security.verify_password(PASSWORD, password_hash)


def test_the_link_verifies_the_email(client, mailbox):
    register(client)
    token = link_token(mailbox.sent[0])

    response = verify(client, token)
    assert response.status_code == 200
    assert response.json() == {"verified": True, "email": "ana@example.com", "updated": True}
    assert sql("SELECT is_email_verified FROM users") == [(True,)]
    # Opening the link a second time is fine; nothing changes.
    assert verify(client, token).json()["updated"] is False


def test_a_bad_or_expired_link_is_400(client):
    register(client)
    secret = client.app.state.settings.jwt_secret
    expired, _ = security.create_token(secret, 1, "email_verify", timedelta(seconds=-1))
    other_kind, _ = security.create_token(secret, 1, "access", timedelta(minutes=15))
    for token in ("not-a-token", expired, other_kind):
        response = verify(client, token)
        assert response.status_code == 400
        assert response.json() == {"error": {"code": "400", "detail": "Invalid or expired link"}}
    assert sql("SELECT is_email_verified FROM users") == [(False,)]


def test_registering_a_verified_email_again_is_409(client, mailbox):
    register(client)
    verify(client, link_token(mailbox.sent[0]))
    response = register(client, password="another password")
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "409", "detail": "Email already registered"}}
    assert len(mailbox.sent) == 1  # no new email


def test_registering_again_before_verifying_keeps_one_account_and_sends_a_new_link(client, mailbox):
    register(client)
    [(first_hash,)] = sql("SELECT password_hash FROM users")
    assert register(client, password="a newer password").status_code == 202

    assert len(mailbox.sent) == 2
    # Still one row: one account. The newest password wins (whoever reads the inbox decides),
    # and token_version went up, so only the newest link works.
    [(newest_hash, version)] = sql("SELECT password_hash, token_version FROM users")
    assert newest_hash != first_hash
    assert security.verify_password("a newer password", newest_hash)
    assert version == 2
    assert verify(client, link_token(mailbox.sent[-1])).status_code == 200


def test_emails_are_kept_in_lower_case(client, mailbox):
    register(client, email="Ana.Smith@Example.COM")
    assert sql("SELECT email FROM users") == [("ana.smith@example.com",)]
    assert mailbox.sent[0]["to"] == "ana.smith@example.com"
    assert register(client, email="ana.smith@example.com").status_code == 202  # same account
    assert sql("SELECT count(*) FROM users") == [(1,)]


def test_register_checks_the_email_and_the_password_length(client, mailbox):
    bad_email = client.post("/api/auth/register", json={"email": "ana", "password": PASSWORD})
    assert bad_email.status_code == 422
    assert bad_email.json()["error"]["detail"].startswith("body → email: value is not a valid")
    short = register(client, password="short")
    assert short.status_code == 422
    assert short.json()["error"]["detail"] == (
        "body → password: String should have at least 8 characters"
    )
    assert mailbox.sent == []


def test_register_allows_5_requests_a_minute_per_ip(client):
    for number in range(5):
        assert register(client, email=f"user{number}@example.com").status_code == 202
    response = register(client, email="user5@example.com")
    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "429", "detail": "Rate limit exceeded: 5 per 1 minute"}
    }


def test_login_gives_an_access_token_and_a_refresh_token(client, mailbox):
    sign_up(client, mailbox)
    response = login(client)
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "bearer"

    access = claims(client, tokens["access_token"], "access")
    assert (access["sub"], access["scope"], access["ver"]) == ("1", "access", 1)
    assert access["exp"] - access["iat"] == 15 * 60  # 15 minutes
    refresh = claims(client, tokens["refresh_token"], "refresh")
    assert refresh["exp"] - refresh["iat"] == 30 * 24 * 3600  # 30 days
    # The refresh token is remembered by its id (jti); the token itself is not stored.
    assert sql("SELECT user_id, jti, token_version, revoked FROM refresh_tokens") == [
        (1, refresh["jti"], 1, False)
    ]


def test_login_is_refused_with_403_until_the_email_is_verified(client, mailbox):
    register(client)
    response = login(client)
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "403", "detail": "Email not verified"}}
    # With a wrong password the answer is 401: only the owner learns "not verified".
    assert login(client, password="wrong password").status_code == 401

    verify(client, link_token(mailbox.sent[0]))
    assert login(client).status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(client, mailbox):
    sign_up(client, mailbox)
    wrong_password = login(client, password="wrong password")
    unknown_email = login(client, email="nobody@example.com")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert (
        wrong_password.json()
        == unknown_email.json()
        == {"error": {"code": "401", "detail": "Invalid email or password"}}
    )


def test_a_deleted_account_cannot_log_in(client, mailbox):
    sign_up(client, mailbox)
    sql("UPDATE users SET status = 'deleted'")
    response = login(client)
    assert response.status_code == 401
    assert response.json()["error"]["detail"] == "Invalid email or password"


def test_login_uses_the_newest_password_after_registering_twice(client, mailbox):
    register(client, password="first password")
    register(client, password="second password")
    verify(client, link_token(mailbox.sent[-1]))
    assert login(client, password="first password").status_code == 401
    assert login(client, password="second password").status_code == 200


def test_an_older_link_stops_working_once_someone_signs_up_again(client, mailbox):
    # 1. The owner signs up and gets link 1.
    register(client, password="owner password")
    # 2. Before the owner opens it, someone else signs up with the same email and their own
    #    password. Link 2 goes to the owner's inbox, so the other person never sees it.
    register(client, password="intruder password")
    first_link, second_link = (link_token(email) for email in mailbox.sent)
    # 3. The owner opens link 1: it was made for the old password, so it no longer works.
    response = verify(client, first_link)
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "400", "detail": "Invalid or expired link"}}
    assert sql("SELECT is_email_verified, token_version FROM users") == [(False, 2)]
    # 4. So the other person's password does not open the account.
    assert login(client, password="intruder password").status_code == 403

    # The owner signs up again (this is how a new link is asked for): link 3 replaces link 2.
    register(client, password="owner password")
    third_link = link_token(mailbox.sent[-1])
    assert verify(client, second_link).status_code == 400
    assert verify(client, third_link).json()["updated"] is True
    assert login(client, password="intruder password").status_code == 401
    assert login(client, password="owner password").status_code == 200
    # Only the newest link stays valid, even after verifying.
    assert verify(client, first_link).status_code == 400
    assert verify(client, third_link).json()["updated"] is False


async def wait_for_requests_on_the_lock(engine, count: int) -> None:
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
    raise AssertionError(f"{count} request(s) should be waiting for the lock, not {waiting}")


async def open_link_and_sign_up_at_the_same_moment(first: str) -> dict:
    """The owner opens link 1 while someone else signs up with the same email and their own
    password. `first` is the request PostgreSQL serves first. Returns both status codes."""
    mailbox = FakeMailer()
    app = build_app(database_url=TEST_DATABASE_URL)
    app.dependency_overrides[get_mailer] = lambda: mailbox
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    # Both requests go to the real app at once, in this one event loop.
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as http:
        owner = {"email": "ana@example.com", "password": "owner password"}
        await http.post("/api/auth/register", json=owner)
        first_link = link_token(mailbox.sent[0])
        requests = {
            "verify": lambda: http.get("/api/auth/verify", params={"token": first_link}),
            "register": lambda: http.post(
                "/api/auth/register", json={**owner, "password": "intruder password"}
            ),
        }
        async with engine.connect() as gate:
            # The gate holds the account's row locked, like a slow request would, so both
            # requests reach the database while the other one is still waiting there.
            await gate.execute(text("SELECT id FROM users FOR UPDATE"))
            tasks = {}
            for name in (first, *(other for other in requests if other != first)):
                tasks[name] = asyncio.create_task(requests[name]())
                await wait_for_requests_on_the_lock(engine, len(tasks))
            await gate.commit()  # PostgreSQL now lets them through one at a time, in order
            answers = {name: (await task).status_code for name, task in tasks.items()}
    await app.state.engine.dispose()
    await engine.dispose()
    return answers


@pytest.mark.parametrize("first", ["verify", "register"])
def test_opening_a_link_and_signing_up_at_the_same_moment_never_mix(first):
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    answers = asyncio.run(open_link_and_sign_up_at_the_same_moment(first))

    [(verified, password_hash, version)] = sql(
        "SELECT is_email_verified, password_hash, token_version FROM users"
    )
    if first == "verify":
        # Link 1 wins: verified with the owner's password, and the sign-up is refused.
        assert answers == {"verify": 200, "register": 409}
        assert (verified, version) == (True, 1)
        assert security.verify_password("owner password", password_hash)
    else:
        # The sign-up wins: a new password, so link 1 is now too old and verifies nothing.
        assert answers == {"register": 202, "verify": 400}
        assert (verified, version) == (False, 2)
        assert security.verify_password("intruder password", password_hash)


def test_login_allows_10_requests_a_minute_per_ip(client):
    for _ in range(10):
        assert login(client, email="nobody@example.com").status_code == 401
    response = login(client, email="nobody@example.com")
    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "429", "detail": "Rate limit exceeded: 10 per 1 minute"}
    }


def test_refresh_gives_a_new_pair_and_retires_the_old_refresh_token(client, mailbox):
    sign_up(client, mailbox)
    first = login(client).json()
    response = refresh(client, first["refresh_token"])
    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]

    old_jti = claims(client, first["refresh_token"], "refresh")["jti"]
    new_jti = claims(client, second["refresh_token"], "refresh")["jti"]
    assert sql("SELECT jti, revoked FROM refresh_tokens ORDER BY id") == [
        (old_jti, True),
        (new_jti, False),
    ]
    assert refresh(client, second["refresh_token"]).status_code == 200  # the new one works


def test_a_reused_refresh_token_is_401(client, mailbox):
    sign_up(client, mailbox)
    old = login(client).json()["refresh_token"]
    assert refresh(client, old).status_code == 200
    response = refresh(client, old)  # the same token a second time
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "401", "detail": "Invalid or expired token"}}


def test_refresh_refuses_a_bad_an_expired_or_an_access_token(client, mailbox):
    sign_up(client, mailbox)
    access_token = login(client).json()["access_token"]
    secret = client.app.state.settings.jwt_secret
    expired, _ = security.create_token(secret, 1, "refresh", timedelta(seconds=-1))
    for token in ("not-a-token", expired, access_token):
        assert refresh(client, token).status_code == 401


def test_logout_revokes_the_refresh_token(client, mailbox):
    sign_up(client, mailbox)
    tokens = login(client).json()
    response = logout(client, tokens["refresh_token"])
    assert response.status_code == 204
    assert response.content == b""
    assert sql("SELECT revoked FROM refresh_tokens") == [(True,)]
    assert refresh(client, tokens["refresh_token"]).status_code == 401
    assert logout(client, tokens["refresh_token"]).status_code == 204  # twice is fine


def test_logout_with_no_token_or_a_bad_one_still_answers_204(client):
    assert client.post("/api/auth/logout").status_code == 204  # no body at all
    assert client.post("/api/auth/logout", json={}).status_code == 204  # no token
    assert logout(client, "not-a-token").status_code == 204


def test_refresh_allows_20_requests_a_minute_per_ip(client):
    for _ in range(20):
        assert refresh(client, "not-a-token").status_code == 401
    response = refresh(client, "not-a-token")
    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "429", "detail": "Rate limit exceeded: 20 per 1 minute"}
    }


def test_a_protected_route_without_a_token_is_401(client):
    response = who_am_i(client, None)
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "401", "detail": "Not authenticated"}}
    assert response.headers["www-authenticate"] == "Bearer"


def test_raising_token_version_ends_every_older_token(client, mailbox):
    sign_up(client, mailbox)
    tokens = login(client).json()
    assert who_am_i(client, tokens["access_token"]).status_code == 200
    # What a password change or reset will do (BE-04).
    sql("UPDATE users SET token_version = token_version + 1")
    assert who_am_i(client, tokens["access_token"]).status_code == 401
    assert refresh(client, tokens["refresh_token"]).status_code == 401
    # A new login gives tokens with the new version, and they work.
    assert who_am_i(client, login(client).json()["access_token"]).status_code == 200


def test_an_expired_access_token_is_refused(client, mailbox):
    sign_up(client, mailbox)
    secret = client.app.state.settings.jwt_secret
    expired, _ = security.create_token(secret, 1, "access", timedelta(seconds=-1), ver=1)
    response = who_am_i(client, expired)
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "401", "detail": "Invalid or expired token"}}


def test_a_bad_token_or_a_refresh_token_does_not_open_protected_routes(client, mailbox):
    sign_up(client, mailbox)
    refresh_token = login(client).json()["refresh_token"]
    for token in ("not-a-token", refresh_token):
        assert who_am_i(client, token).status_code == 401


def test_a_deleted_account_loses_access_at_once(client, mailbox):
    sign_up(client, mailbox)
    tokens = login(client).json()
    sql("UPDATE users SET status = 'deleted'")
    assert who_am_i(client, tokens["access_token"]).status_code == 401
    assert refresh(client, tokens["refresh_token"]).status_code == 401
