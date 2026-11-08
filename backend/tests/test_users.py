"""/api/users/me on a real database: read, change and delete my own profile.

Each test starts with an empty users table, so these tests use TEST_DATABASE_URL only and are
skipped without it (conftest.py says how to start one). The users are made up: they are added
straight to the database, already verified, and log in through the real /api/auth/login.
"""

from datetime import date, timedelta

import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi.testclient import TestClient

from app.auth import security
from app.users.schemas import age_on

pytestmark = needs_database

PASSWORD = "correct horse battery"
# Argon2 is slow on purpose, so the hash is made once and shared by every test user.
PASSWORD_HASH = security.hash_password(PASSWORD)

# The profile every test user starts with, as the API writes it in JSON.
ANA = {
    "first_name": "Ana",
    "last_name": "Silva",
    "position": "Barista",
    "birth_date": "1995-03-14",
    "bio": "Coffee first.",
}

# A new valid value for each field that PATCH can change.
NEW = {
    "first_name": "Ana Maria",
    "last_name": "Costa",
    "position": "Head barista",
    "birth_date": "1990-07-01",
    "bio": "Tea now.",
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
        **{**ANA, "birth_date": date.fromisoformat(ANA["birth_date"])},
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


def patch_me(client, tokens: dict, body: dict):
    return client.patch("/api/users/me", json=body, headers=bearer(tokens))


def delete_me(client, tokens: dict):
    return client.delete("/api/users/me", headers=bearer(tokens))


def profile_in_db(email: str) -> dict:
    """The five profile columns of this user, as stored in the users table."""
    [row] = sql(
        "SELECT first_name, last_name, position, birth_date::text AS birth_date, bio"
        " FROM users WHERE email = :email",
        email=email,
    )
    return dict(row._mapping)


def profile_in(response) -> dict:
    """The five profile fields of a UserOut answer."""
    return {field: response.json()[field] for field in ANA}


def years_ago(years: int) -> date:
    """Today's date, that many years back (28 February if today is 29 February)."""
    today = date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 February, in a year that has none
        return today.replace(year=today.year - years, day=28)


def test_get_me_returns_my_profile(client, ana):
    response = get_me(client, ana)
    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "email": "ana@example.com",
        **ANA,
        "avatar_object_key": None,
        "is_email_verified": True,
    }


def test_user_out_leaves_out_the_dropped_and_the_secret_fields(client, ana):
    fields = set(get_me(client, ana).json())
    # Dropped from the contract (BE-05).
    assert not fields & {"phone", "is_phone_verified", "username", "account_number"}
    # Never sent at all.
    assert not fields & {"password_hash", "token_version", "status"}


@pytest.mark.parametrize("field", list(NEW))
def test_patch_changes_only_the_field_that_is_sent(client, ana, field):
    response = patch_me(client, ana, {field: NEW[field]})
    assert response.status_code == 200
    expected = {**ANA, field: NEW[field]}
    assert profile_in(response) == expected
    assert profile_in_db("ana@example.com") == expected


def test_patch_changes_several_fields_at_once(client, ana):
    body = {"first_name": "Ana Maria", "position": "Head barista", "bio": "Tea now."}
    response = patch_me(client, ana, body)
    assert response.status_code == 200
    assert profile_in(response) == {**ANA, **body}
    assert profile_in_db("ana@example.com") == {**ANA, **body}


def test_patch_with_an_empty_body_changes_nothing(client, ana):
    response = patch_me(client, ana, {})
    assert response.status_code == 200
    assert profile_in(response) == ANA
    assert profile_in_db("ana@example.com") == ANA


def test_patch_without_a_body_is_422(client, ana):
    response = client.patch("/api/users/me", headers=bearer(ana))
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "422", "detail": "body: Field required"}}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "eve@example.com"),
        ("status", "deleted"),
        ("token_version", 99),
        ("is_email_verified", False),
        ("password_hash", "not-a-hash"),
        ("avatar_object_key", "avatars/2/someone-else.png"),
        ("id", 2),
        # The fields dropped from UserOut cannot be sent either.
        ("phone", "+971500000000"),
        ("username", "ana"),
    ],
)
def test_patch_refuses_any_other_field_and_then_changes_nothing(client, ana, field, value):
    response = patch_me(client, ana, {"bio": "Changed?", field: value})
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "422", "detail": f"body → {field}: Extra inputs are not permitted"}
    }
    # The whole request is refused, the valid bio too.
    assert profile_in_db("ana@example.com") == ANA
    assert sql("SELECT email, status, token_version FROM users") == [
        ("ana@example.com", "active", 1)
    ]


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"first_name": ""}, "body → first_name: String should have at least 1 character"),
        ({"first_name": "   "}, "body → first_name: String should have at least 1 character"),
        ({"last_name": "x" * 51}, "body → last_name: String should have at most 50 characters"),
        ({"position": "x" * 101}, "body → position: String should have at most 100 characters"),
        ({"bio": "x" * 501}, "body → bio: String should have at most 500 characters"),
        ({"first_name": 42}, "body → first_name: Input should be a valid string"),
        # Only bio can be emptied with null.
        ({"first_name": None}, "body → first_name: Input should be a valid string"),
        ({"position": None}, "body → position: Input should be a valid string"),
        ({"birth_date": None}, "body → birth_date: Input should be a valid date"),
    ],
)
def test_patch_refuses_bad_values_and_then_changes_nothing(client, ana, body, detail):
    response = patch_me(client, ana, body)
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "422", "detail": detail}}
    assert profile_in_db("ana@example.com") == ANA


@pytest.mark.parametrize("birth_date", ["14/03/1995", "1995-02-30", "yesterday"])
def test_patch_refuses_a_birth_date_that_is_not_a_date(client, ana, birth_date):
    response = patch_me(client, ana, {"birth_date": birth_date})
    assert response.status_code == 422
    assert response.json()["error"]["detail"].startswith("body → birth_date: Input should be")
    assert profile_in_db("ana@example.com") == ANA


def test_patch_removes_the_spaces_around_the_text(client, ana):
    response = patch_me(client, ana, {"first_name": "  Ana Maria ", "bio": " Tea now.  "})
    assert response.status_code == 200
    stored = profile_in_db("ana@example.com")
    assert (stored["first_name"], stored["bio"]) == ("Ana Maria", "Tea now.")


def test_bio_can_be_emptied_with_null(client, ana):
    response = patch_me(client, ana, {"bio": None})
    assert response.status_code == 200
    assert response.json()["bio"] is None
    assert profile_in_db("ana@example.com") == {**ANA, "bio": None}


UNDER_18 = {
    "error": {"code": "422", "detail": "body → birth_date: You must be at least 18 years old"}
}


def test_a_user_under_18_is_refused(client, ana):
    response = patch_me(client, ana, {"birth_date": years_ago(17).isoformat()})
    assert response.status_code == 422
    assert response.json() == UNDER_18
    assert profile_in_db("ana@example.com") == ANA


def test_a_birth_date_in_the_future_is_refused(client, ana):
    tomorrow = date.today() + timedelta(days=1)
    response = patch_me(client, ana, {"birth_date": tomorrow.isoformat()})
    assert response.status_code == 422
    assert response.json() == UNDER_18


def test_turning_18_today_is_allowed_but_tomorrow_is_not(client, ana):
    turns_18_tomorrow = years_ago(18) + timedelta(days=1)
    response = patch_me(client, ana, {"birth_date": turns_18_tomorrow.isoformat()})
    assert response.json() == UNDER_18
    response = patch_me(client, ana, {"birth_date": years_ago(18).isoformat()})
    assert response.status_code == 200
    assert profile_in_db("ana@example.com")["birth_date"] == years_ago(18).isoformat()


def test_age_counts_only_full_years():
    born = date(2008, 11, 9)
    assert age_on(date(2026, 11, 8), born) == 17  # the day before the 18th birthday
    assert age_on(date(2026, 11, 9), born) == 18  # the birthday itself
    leap_day = date(2008, 2, 29)  # in other years, the birthday counts from 1 March
    assert age_on(date(2026, 2, 28), leap_day) == 17
    assert age_on(date(2026, 3, 1), leap_day) == 18


def test_patch_changes_only_my_own_row(client, ana):
    make_user("ben@example.com")
    assert patch_me(client, ana, NEW).status_code == 200
    assert profile_in_db("ana@example.com") == NEW
    assert profile_in_db("ben@example.com") == ANA


def test_delete_marks_the_account_deleted_and_keeps_the_row(client, ana):
    response = delete_me(client, ana)
    assert response.status_code == 204
    assert response.content == b""
    # A soft delete: the row and the profile are still there, only the status changed.
    assert sql("SELECT email, status FROM users") == [("ana@example.com", "deleted")]
    assert profile_in_db("ana@example.com") == ANA


def test_a_deleted_account_cannot_log_in(client, ana):
    delete_me(client, ana)
    response = login(client, "ana@example.com")
    # The same answer as a wrong password: login does not say the account ever existed.
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "401", "detail": "Invalid email or password"}}


def test_after_delete_the_old_tokens_stop_working_at_once(client, ana):
    assert delete_me(client, ana).status_code == 204
    # The access token is less than 15 minutes old, but it opens nothing any more...
    assert get_me(client, ana).status_code == 401
    assert patch_me(client, ana, {"bio": "Still here?"}).status_code == 401
    assert delete_me(client, ana).status_code == 401
    # ...and the refresh token cannot get a new pair.
    response = client.post("/api/auth/refresh", json={"refresh_token": ana["refresh_token"]})
    assert response.status_code == 401
    assert profile_in_db("ana@example.com") == ANA


def test_a_deleted_accounts_email_stays_taken(client, ana):
    delete_me(client, ana)
    response = client.post(
        "/api/auth/register", json={"email": "ana@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409


def test_delete_deletes_only_my_own_account(client, ana):
    make_user("ben@example.com")
    assert delete_me(client, ana).status_code == 204
    assert sql("SELECT email, status FROM users ORDER BY id") == [
        ("ana@example.com", "deleted"),
        ("ben@example.com", "active"),
    ]
    assert login(client, "ben@example.com").status_code == 200


# Every /users/me route, with a body that would be accepted, so only the token is wrong.
ME_ROUTES = [("GET", None), ("PATCH", {"bio": "Hi"}), ("DELETE", None)]


@pytest.mark.parametrize(("method", "body"), ME_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not.a.token"}])
def test_every_users_me_route_needs_a_valid_access_token(client, ana, method, body, headers):
    response = client.request(method, "/api/users/me", json=body, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "401"
