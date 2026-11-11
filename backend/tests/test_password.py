"""Password change, forgot and reset on a real database (BE-04).

Each test starts with an empty users table, so these tests use TEST_DATABASE_URL only and are
skipped without it (conftest.py says how to start one). The users are made up: they are added
straight to the database, already verified, and log in through the real /api/auth/login.
"""

import hashlib
import re
from datetime import timedelta

import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi.testclient import TestClient

from app.auth import security
from app.core.limiter import limiter

pytestmark = needs_database

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new password"
# Argon2 is slow on purpose, so the hash is made once and shared by every test user.
PASSWORD_HASH = security.hash_password(PASSWORD)
FORGOT_ANSWER = {"message": "If this email has an account, a reset link is on its way"}


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


@pytest.fixture
def client():
    """This file's client: an app on the test database, with no users yet."""
    # CASCADE also empties refresh_tokens and password_reset_tokens.
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    with TestClient(build_app(database_url=TEST_DATABASE_URL)) as test_client:
        yield test_client


def make_user(email: str = "ana@example.com", verified: bool = True) -> None:
    """An account with PASSWORD, added straight to the database."""
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :password_hash, :verified)",
        email=email,
        password_hash=PASSWORD_HASH,
        verified=verified,
    )


def login(client, email="ana@example.com", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


@pytest.fixture
def ana(client) -> dict:
    """Ana's account, logged in: her access and refresh tokens."""
    make_user()
    response = login(client)
    assert response.status_code == 200
    return response.json()


def bearer(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def get_me(client, access_token: str):
    return client.get("/api/users/me", headers=bearer(access_token))


def refresh(client, refresh_token: str):
    return client.post("/api/auth/refresh", json={"refresh_token": refresh_token})


def change_password(client, access_token: str, current=PASSWORD, new=NEW_PASSWORD):
    body = {"current_password": current, "new_password": new}
    return client.post("/api/auth/change-password", json=body, headers=bearer(access_token))


def stored_password_and_version() -> tuple[str, int]:
    [(password_hash, version)] = sql("SELECT password_hash, token_version FROM users")
    return password_hash, version


def forgot_password(client, email="ana@example.com"):
    return client.post("/api/auth/forgot-password", json={"email": email})


def sent_emails(client) -> list[dict]:
    """The emails the app sent (build_app puts a test mailbox in place of the mailer)."""
    return client.app.state.test_mailbox.sent


def reset_token_in(email: dict) -> str:
    """The token of the email's link, which must open the frontend's /reset-password page."""
    match = re.search(r"https://localhost/reset-password\?token=(\S+)", email["body"])
    assert match, email["body"]
    return match.group(1)


# --- POST /api/auth/change-password ---------------------------------------------------------


def test_change_password_answers_204_and_only_the_new_password_works(client, ana):
    response = change_password(client, ana["access_token"])
    assert response.status_code == 204
    assert response.content == b""

    password_hash, version = stored_password_and_version()
    assert password_hash.startswith("$argon2id$")  # a new Argon2id hash, never the text
    assert security.verify_password(NEW_PASSWORD, password_hash)
    assert version == 2  # token_version + 1
    assert login(client).status_code == 401  # the old password
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_after_a_change_every_old_token_of_the_user_is_refused(client, ana):
    laptop, phone = ana, login(client).json()  # logged in on two devices
    assert change_password(client, laptop["access_token"]).status_code == 204

    for device in (laptop, phone):
        response = get_me(client, device["access_token"])
        assert response.status_code == 401
        assert response.json() == {"error": {"code": "401", "detail": "Invalid or expired token"}}
        assert refresh(client, device["refresh_token"]).status_code == 401
    # A new login gives tokens that work.
    tokens = login(client, password=NEW_PASSWORD).json()
    assert get_me(client, tokens["access_token"]).status_code == 200


def test_a_wrong_current_password_is_400_and_changes_nothing(client, ana):
    response = change_password(client, ana["access_token"], current="not my password")
    # 400, not 401: the user stays logged in and can try again.
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "400", "detail": "Wrong current password"}}

    password_hash, version = stored_password_and_version()
    assert (password_hash, version) == (PASSWORD_HASH, 1)
    assert get_me(client, ana["access_token"]).status_code == 200
    assert refresh(client, ana["refresh_token"]).status_code == 200


def test_change_password_needs_a_logged_in_user(client, ana):
    no_token = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert no_token.status_code == 401
    assert no_token.json() == {"error": {"code": "401", "detail": "Not authenticated"}}
    assert change_password(client, "not-a-token").status_code == 401
    # The refresh token is not an access token.
    assert change_password(client, ana["refresh_token"]).status_code == 401
    assert stored_password_and_version() == (PASSWORD_HASH, 1)


@pytest.mark.parametrize(
    ("new_password", "detail"),
    [
        ("short", "body → new_password: String should have at least 8 characters"),
        ("x" * 129, "body → new_password: String should have at most 128 characters"),
    ],
)
def test_the_new_password_follows_the_sign_up_rules(client, ana, new_password, detail):
    response = change_password(client, ana["access_token"], new=new_password)
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "422", "detail": detail}}
    assert stored_password_and_version() == (PASSWORD_HASH, 1)


def test_change_password_allows_5_requests_a_minute_per_ip(client, ana):
    for _ in range(5):
        assert change_password(client, ana["access_token"], current="guess").status_code == 400
    response = change_password(client, ana["access_token"], current="guess")
    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "429", "detail": "Rate limit exceeded: 5 per 1 minute"}
    }


# --- POST /api/auth/forgot-password ---------------------------------------------------------


def test_forgot_password_answers_202_and_emails_a_link_to_the_frontend(client):
    make_user()
    response = forgot_password(client, "Ana@Example.com")  # emails are compared in lower case
    assert response.status_code == 202
    assert response.json() == FORGOT_ANSWER

    [email] = sent_emails(client)
    assert email["to"] == "ana@example.com"
    assert email["subject"] == "Reset your WOZU password"
    assert "The link works once, for 60 minutes." in email["body"]
    # The token: 64 random characters that can go into a link as they are.
    assert re.fullmatch(r"[A-Za-z0-9_-]{64}", reset_token_in(email))


def test_only_a_hash_of_the_reset_token_is_stored_for_1_hour(client):
    make_user()
    forgot_password(client)
    token = reset_token_in(sent_emails(client)[0])

    [(user_id, stored, lifetime, used_at)] = sql(
        "SELECT user_id, token, expires_at - created_at, used_at FROM password_reset_tokens"
    )
    assert user_id == 1
    # The database has the token's SHA-256, never the token: reading the table gives no link.
    assert stored != token
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert abs(lifetime - timedelta(hours=1)) < timedelta(seconds=5)
    assert used_at is None


def test_each_request_gets_its_own_new_token(client):
    make_user()
    forgot_password(client)
    forgot_password(client)
    first, second = (reset_token_in(email) for email in sent_emails(client))
    assert first != second
    assert sql("SELECT count(*) FROM password_reset_tokens") == [(2,)]


def test_forgot_password_answers_the_same_202_for_unknown_unverified_and_deleted_emails(client):
    make_user("ana@example.com")
    make_user("ben@example.com", verified=False)
    make_user("cara@example.com")
    sql("UPDATE users SET status = 'deleted' WHERE email = 'cara@example.com'")
    known = forgot_password(client, "ana@example.com")

    for email in ("nobody@example.com", "ben@example.com", "cara@example.com"):
        limiter.reset()  # 4 requests in this test, over the limit of 3 a minute
        response = forgot_password(client, email)
        # The same answer as for a real account: nobody learns whether an email has one.
        assert (response.status_code, response.json()) == (known.status_code, known.json())
        assert (response.status_code, response.json()) == (202, FORGOT_ANSWER)
    # Only Ana got an email and a reset token.
    assert [email["to"] for email in sent_emails(client)] == ["ana@example.com"]
    assert sql("SELECT user_id FROM password_reset_tokens") == [(1,)]


def test_forgot_password_with_a_bad_email_is_422(client):
    response = forgot_password(client, "ana")
    assert response.status_code == 422
    assert response.json()["error"]["detail"].startswith("body → email: value is not a valid")
    assert sent_emails(client) == []


def test_forgot_password_allows_3_requests_a_minute_per_ip(client):
    for number in range(3):
        assert forgot_password(client, f"user{number}@example.com").status_code == 202
    response = forgot_password(client, "user3@example.com")
    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "429", "detail": "Rate limit exceeded: 3 per 1 minute"}
    }


# --- POST /api/auth/reset-password ----------------------------------------------------------

INVALID_LINK = {"error": {"code": "400", "detail": "Invalid or expired link"}}


def reset_password(client, token: str, new=NEW_PASSWORD):
    return client.post("/api/auth/reset-password", json={"token": token, "new_password": new})


def ask_for_a_reset_link(client, email="ana@example.com") -> str:
    """POST /forgot-password, then read the token from the newest email's link."""
    assert forgot_password(client, email).status_code == 202
    return reset_token_in(sent_emails(client)[-1])


def test_the_whole_reset_journey(client, ana):
    # 1. Ana forgot her password: she asks for a link and gets an email.
    token = ask_for_a_reset_link(client)
    # 2. The link opens the frontend's page; it sends the token and her new password.
    response = reset_password(client, token)
    assert response.status_code == 204
    assert response.content == b""
    # 3. The new password works, the old one does not.
    assert login(client).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200

    password_hash, version = stored_password_and_version()
    assert security.verify_password(NEW_PASSWORD, password_hash)
    assert version == 2  # token_version + 1
    assert sql("SELECT used_at IS NOT NULL FROM password_reset_tokens") == [(True,)]


def test_after_a_reset_every_old_token_of_the_user_is_refused(client, ana):
    laptop, phone = ana, login(client).json()  # logged in on two devices
    assert reset_password(client, ask_for_a_reset_link(client)).status_code == 204

    for device in (laptop, phone):
        assert get_me(client, device["access_token"]).status_code == 401
        assert refresh(client, device["refresh_token"]).status_code == 401


def test_a_reset_link_works_only_once(client, ana):
    token = ask_for_a_reset_link(client)
    assert reset_password(client, token).status_code == 204

    again = reset_password(client, token, new="someone else's password")
    assert again.status_code == 400
    assert again.json() == INVALID_LINK
    assert login(client, password="someone else's password").status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_an_expired_reset_link_is_400_and_changes_nothing(client, ana):
    token = ask_for_a_reset_link(client)
    # As if the hour had passed.
    sql("UPDATE password_reset_tokens SET expires_at = now() - interval '1 second'")

    response = reset_password(client, token)
    assert response.status_code == 400
    assert response.json() == INVALID_LINK
    assert stored_password_and_version() == (PASSWORD_HASH, 1)
    assert get_me(client, ana["access_token"]).status_code == 200


def test_a_wrong_reset_token_is_400_and_changes_nothing(client, ana):
    token = ask_for_a_reset_link(client)
    [(stored_hash,)] = sql("SELECT token FROM password_reset_tokens")
    # Made up, empty, a real-looking token we never sent, and the value in the database
    # (someone who read the table still cannot use it).
    for wrong in ("not-a-token", "", security.new_reset_token(), stored_hash):
        response = reset_password(client, wrong)
        assert response.status_code == 400
        assert response.json() == INVALID_LINK
    assert stored_password_and_version() == (PASSWORD_HASH, 1)
    # None of them used up the real link.
    assert reset_password(client, token).status_code == 204


def test_a_bad_new_password_is_422_and_does_not_use_up_the_link(client, ana):
    token = ask_for_a_reset_link(client)
    response = reset_password(client, token, new="short")
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "422",
            "detail": "body → new_password: String should have at least 8 characters",
        }
    }
    assert reset_password(client, token).status_code == 204


def test_a_reset_link_stops_working_once_the_account_is_deleted(client, ana):
    token = ask_for_a_reset_link(client)
    sql("UPDATE users SET status = 'deleted'")
    response = reset_password(client, token)
    assert response.status_code == 400
    assert response.json() == INVALID_LINK
    assert stored_password_and_version() == (PASSWORD_HASH, 1)


def test_reset_password_allows_5_requests_a_minute_per_ip(client):
    for _ in range(5):
        assert reset_password(client, "not-a-token").status_code == 400
    response = reset_password(client, "not-a-token")
    assert response.status_code == 429
    assert response.json() == {
        "error": {"code": "429", "detail": "Rate limit exceeded: 5 per 1 minute"}
    }
