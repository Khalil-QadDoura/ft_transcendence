"""Password change, forgot and reset on a real database (BE-04).

Each test starts with an empty users table, so these tests use TEST_DATABASE_URL only and are
skipped without it (conftest.py says how to start one). The users are made up: they are added
straight to the database, already verified, and log in through the real /api/auth/login.
"""

import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi.testclient import TestClient

from app.auth import security

pytestmark = needs_database

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new password"
# Argon2 is slow on purpose, so the hash is made once and shared by every test user.
PASSWORD_HASH = security.hash_password(PASSWORD)


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
