"""/api/users/me on a real database: read, change and delete my own profile.

Each test starts with an empty users table, so these tests use TEST_DATABASE_URL only and are
skipped without it (conftest.py says how to start one). The users are made up: they are added
straight to the database, already verified, and log in through the real /api/auth/login.
"""

from datetime import date

import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi.testclient import TestClient

from app.auth import security

pytestmark = needs_database

PASSWORD = "correct horse battery"
# Argon2 is slow on purpose, so the hash is made once and shared by every test user.
PASSWORD_HASH = security.hash_password(PASSWORD)

# The profile every test user starts with.
ANA = {
    "first_name": "Ana",
    "last_name": "Silva",
    "position": "Barista",
    "birth_date": date(1995, 3, 14),
    "bio": "Coffee first.",
}


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    alembic("upgrade", "head")


@pytest.fixture
def client():
    """This file's client: an app on the test database, with no users yet."""
    # CASCADE also empties refresh_tokens and every other table that points at users.
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    with TestClient(build_app(database_url=TEST_DATABASE_URL)) as test_client:
        yield test_client


def make_user(email: str) -> None:
    """A verified account with the ANA profile, added straight to the database."""
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified,"
        " first_name, last_name, position, birth_date, bio)"
        " VALUES (:email, :password_hash, true,"
        " :first_name, :last_name, :position, :birth_date, :bio)",
        email=email,
        password_hash=PASSWORD_HASH,
        **ANA,
    )


def login(client, email: str):
    return client.post("/api/auth/login", json={"email": email, "password": PASSWORD})


@pytest.fixture
def ana(client) -> dict:
    """Ana's account, logged in: her access and refresh tokens."""
    make_user("ana@example.com")
    response = login(client, "ana@example.com")
    assert response.status_code == 200
    return response.json()


def bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def get_me(client, tokens: dict):
    return client.get("/api/users/me", headers=bearer(tokens))


def test_get_me_returns_my_profile(client, ana):
    response = get_me(client, ana)
    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "email": "ana@example.com",
        "first_name": "Ana",
        "last_name": "Silva",
        "position": "Barista",
        "birth_date": "1995-03-14",
        "bio": "Coffee first.",
        "avatar_object_key": None,
        "is_email_verified": True,
    }


def test_user_out_leaves_out_the_dropped_and_the_secret_fields(client, ana):
    fields = set(get_me(client, ana).json())
    # Dropped from the contract (BE-05).
    assert not fields & {"phone", "is_phone_verified", "username", "account_number"}
    # Never sent at all.
    assert not fields & {"password_hash", "token_version", "status"}


# Every /users/me route, with a body that would be accepted, so only the token is wrong.
ME_ROUTES = [("GET", None)]


@pytest.mark.parametrize(("method", "body"), ME_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not.a.token"}])
def test_every_users_me_route_needs_a_valid_access_token(client, ana, method, body, headers):
    response = client.request(method, "/api/users/me", json=body, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "401"
