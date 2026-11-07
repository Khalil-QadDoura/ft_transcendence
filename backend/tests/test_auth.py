"""Sign-up and login on a real database: register, email, verify, login, refresh, logout.

Each test starts with an empty users table, so these tests use TEST_DATABASE_URL only and are
skipped without it (conftest.py says how to start one). Emails go to a fake mailer.
"""

import asyncio
import re
from datetime import timedelta

import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import security
from app.core.mailer import get_mailer

pytestmark = needs_database

PASSWORD = "correct horse battery"


class FakeMailer:
    """Stands in for the real mailer: keeps each email instead of sending it."""

    def __init__(self):
        self.sent = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


def sql(statement: str, **params) -> list:
    """Run one SQL statement on the test database; returns its rows."""

    async def run() -> list:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as connection:
            result = await connection.execute(text(statement), params)
            rows = result.all() if result.returns_rows else []
        await engine.dispose()
        return rows

    return asyncio.run(run())


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
    [(newest_hash,)] = sql("SELECT password_hash FROM users")  # still one row: one account
    # The newest password wins (whoever reads the inbox decides).
    assert newest_hash != first_hash
    assert security.verify_password("a newer password", newest_hash)


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
