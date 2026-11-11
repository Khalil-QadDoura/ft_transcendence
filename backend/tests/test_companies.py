"""Tests for the companies domain and BE-21 requirements.

Key verification:
- GET /api/companies/me returns 200 with null (never 404) for job seekers without a company.
- POST /api/companies creates a company (201) and forbids duplicates (409).
- PATCH /api/companies/me updates active company details and enforces ISO country code rules.
- DELETE /api/companies performs idempotent soft deletion (204).
- Unauthenticated requests return 401 (Not authenticated).
- Invalid / expired / revoked tokens return 401 (Invalid or expired token).
- Real database integration tests cover lifecycle and user isolation when PostgreSQL is available.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi.testclient import TestClient

from app.auth import security
from app.auth.deps import get_current_user
from app.companies.models import Company
from app.users.models import User

AUTH_SECRET = "test-only-jwt-secret-0123456789abcdef"
TEST_USER = User(
    id=42,
    email="founder@example.com",
    status="active",
    token_version=1,
    is_email_verified=True,
)
TEST_TOKEN, _ = security.create_token(
    secret=AUTH_SECRET,
    user_id=42,
    scope="access",
    lifetime=timedelta(minutes=15),
    ver=1,
)
AUTH_HEADER = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _make_fake_company(
    id: int = 1,
    owner_user_id: int = 42,
    name: str = "Acme Corp",
    country: str = "United Arab Emirates",
    city: str = "Abu Dhabi",
    country_code: str = "AE",
    status: str = "active",
) -> Company:
    now = datetime.now(UTC)
    c = Company(
        id=id,
        owner_user_id=owner_user_id,
        name=name,
        country=country,
        city=city,
        country_code=country_code,
        status=status,
    )
    c.created_at = now
    c.updated_at = now
    return c


# ── Fast Unit / Route Tests (No DB required) ───────────────────────────────────


def test_unauthenticated_requests_return_401(client):
    """Endpoints require authentication and return 401 when no token is sent."""
    for method, path, kwargs in [
        ("GET", "/api/companies/me", {}),
        ("POST", "/api/companies", {"json": {"name": "New Co"}}),
        (
            "PATCH",
            "/api/companies/me",
            {"json": {"name": "New Co", "country": "UAE", "city": "Abu Dhabi"}},
        ),
        ("DELETE", "/api/companies", {}),
    ]:
        response = getattr(client, method.lower())(path, **kwargs)
        assert response.status_code == 401
        assert response.json()["error"]["detail"] == "Not authenticated"


def test_invalid_tokens_return_401(client):
    """Numeric bearer bypass or invalid tokens return 401."""
    # Test numeric bearer (the specific regression requested by Zaid)
    response = client.get("/api/companies/me", headers={"Authorization": "Bearer 42"})
    assert response.status_code == 401
    assert response.json()["error"]["detail"] == "Invalid or expired token"

    # Test expired token
    expired_token, _ = security.create_token(
        secret=AUTH_SECRET,
        user_id=42,
        scope="access",
        lifetime=timedelta(seconds=-10),
        ver=1,
    )
    response = client.get("/api/companies/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
    assert response.json()["error"]["detail"] == "Invalid or expired token"

    # Test wrong scope (e.g. refresh token sent instead of access token)
    refresh_token, _ = security.create_token(
        secret=AUTH_SECRET,
        user_id=42,
        scope="refresh",
        lifetime=timedelta(days=7),
        ver=1,
    )
    response = client.get("/api/companies/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert response.status_code == 401
    assert response.json()["error"]["detail"] == "Invalid or expired token"


def test_get_my_company_returns_200_null_when_user_has_no_company(client):
    """BE-21 core fix: GET /api/companies/me returns 200 with null instead of 404."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    with patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        response = client.get("/api/companies/me", headers=AUTH_HEADER)

    assert response.status_code == 200
    assert response.json() is None


def test_get_my_company_returns_active_company(client):
    """Employer user gets their active company details."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    fake_company = _make_fake_company()

    with patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = fake_company
        response = client.get("/api/companies/me", headers=AUTH_HEADER)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 1
    assert data["name"] == "Acme Corp"
    assert data["owner_user_id"] == 42
    assert data["status"] == "active"


def test_create_company(client):
    """Creates a new company and returns 201."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    created = _make_fake_company(name="Brand New Co")

    with (
        patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_get,
        patch("app.companies.repo.create", new_callable=AsyncMock) as mock_create,
    ):
        mock_get.return_value = None
        mock_create.return_value = created

        response = client.post(
            "/api/companies",
            json={"name": "Brand New Co", "country": "United Arab Emirates", "city": "Abu Dhabi"},
            headers=AUTH_HEADER,
        )

    assert response.status_code == 201
    assert response.json()["name"] == "Brand New Co"


def test_create_company_duplicate_returns_409(client):
    """Cannot create a second active company if one already exists."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    existing = _make_fake_company()

    with patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = existing
        response = client.post(
            "/api/companies",
            json={"name": "Another Co"},
            headers=AUTH_HEADER,
        )

    assert response.status_code == 409
    assert response.json()["error"]["detail"] == "Active company already exists"


def test_update_company(client):
    """Updates company fields and returns 200."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    company = _make_fake_company(name="Acme Corp")
    updated_company = _make_fake_company(name="Updated Corp", country_code="AE")

    with (
        patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_get,
        patch("app.companies.repo.update_company", new_callable=AsyncMock) as mock_update,
    ):
        mock_get.return_value = company
        mock_update.return_value = updated_company

        response = client.patch(
            "/api/companies/me",
            json={
                "name": "Updated Corp",
                "country": "United Arab Emirates",
                "city": "Abu Dhabi",
                "country_code": "AE",
            },
            headers=AUTH_HEADER,
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Corp"
    assert response.json()["country_code"] == "AE"


def test_update_company_invalid_country_code_returns_422(client):
    """Pydantic rejects invalid ISO country code with 422."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    response = client.patch(
        "/api/companies/me",
        json={
            "name": "Acme Corp",
            "country": "United Arab Emirates",
            "city": "Abu Dhabi",
            "country_code": "XX",  # Invalid
        },
        headers=AUTH_HEADER,
    )
    assert response.status_code == 422


def test_update_company_nonexistent_returns_404(client):
    """PATCH on a user with no company returns 404."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    with patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        response = client.patch(
            "/api/companies/me",
            json={
                "name": "Acme Corp",
                "country": "United Arab Emirates",
                "city": "Abu Dhabi",
            },
            headers=AUTH_HEADER,
        )
    assert response.status_code == 404


def test_delete_company_returns_204(client):
    """Soft deletion returns 204."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    company = _make_fake_company()

    with (
        patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_get,
        patch("app.companies.repo.soft_delete", new_callable=AsyncMock) as mock_delete,
    ):
        mock_get.return_value = company
        response = client.delete("/api/companies", headers=AUTH_HEADER)

    assert response.status_code == 204
    mock_delete.assert_awaited_once()


def test_delete_nonexistent_company_is_idempotent(client):
    """Deleting when no active company exists is a no-op 204."""
    client.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    with patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        response = client.delete("/api/companies", headers=AUTH_HEADER)

    assert response.status_code == 204


def test_openapi_contains_companies_routes(client):
    """The OpenAPI spec documents all company routes under /api/companies."""
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/companies/me" in paths
    assert "/api/companies" in paths


# ── Real Database Tests (Requires live PostgreSQL with PostGIS) ────────────────


PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)


def _seed_db_user(email: str, is_active: bool = True, token_version: int = 1) -> None:
    status_str = "active" if is_active else "deleted"
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified, status, token_version,"
        " first_name, last_name, position, birth_date, bio)"
        " VALUES (:email, :password_hash, true, :status, :token_version,"
        " 'Test', 'User', 'Dev', '1995-01-01', 'Bio')",
        email=email,
        password_hash=PASSWORD_HASH,
        status=status_str,
        token_version=token_version,
    )


@needs_database
def test_company_db_integration_and_isolation():
    """Real PostgreSQL integration: full company lifecycle, auth verification, and isolation."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, companies RESTART IDENTITY CASCADE")

    with TestClient(build_app(database_url=TEST_DATABASE_URL)) as test_client:
        # 1. Seed two verified users in real PostgreSQL
        _seed_db_user("founder@example.com")
        _seed_db_user("jobseeker@example.com")

        # 2. Login to get real signed JWT tokens
        r_founder = test_client.post(
            "/api/auth/login",
            json={"email": "founder@example.com", "password": PASSWORD},
        )
        assert r_founder.status_code == 200
        founder_h = {"Authorization": f"Bearer {r_founder.json()['access_token']}"}

        r_seeker = test_client.post(
            "/api/auth/login",
            json={"email": "jobseeker@example.com", "password": PASSWORD},
        )
        assert r_seeker.status_code == 200
        seeker_h = {"Authorization": f"Bearer {r_seeker.json()['access_token']}"}

        # 3. Job seeker has no company -> 200 null (BE-21 core guarantee)
        res = test_client.get("/api/companies/me", headers=seeker_h)
        assert res.status_code == 200
        assert res.json() is None

        # 4. Numeric bearer bypass returns 401
        res = test_client.get("/api/companies/me", headers={"Authorization": "Bearer 42"})
        assert res.status_code == 401
        assert res.json()["error"]["detail"] == "Invalid or expired token"

        # 5. Founder registers a company -> 201
        res = test_client.post(
            "/api/companies",
            json={
                "name": "Hyperion Ltd",
                "description": "Tech company",
                "country": "United Arab Emirates",
                "city": "Abu Dhabi",
            },
            headers=founder_h,
        )
        assert res.status_code == 201
        cid = res.json()["id"]
        assert res.json()["name"] == "Hyperion Ltd"
        assert res.json()["status"] == "active"

        # 6. Founder reads their company -> 200 with data
        res = test_client.get("/api/companies/me", headers=founder_h)
        assert res.status_code == 200
        assert res.json()["id"] == cid
        assert res.json()["name"] == "Hyperion Ltd"

        # 7. User isolation check: Job seeker still sees 200 null
        res = test_client.get("/api/companies/me", headers=seeker_h)
        assert res.status_code == 200
        assert res.json() is None

        # 8. Duplicate creation fails with 409
        res = test_client.post(
            "/api/companies",
            json={"name": "Second Company"},
            headers=founder_h,
        )
        assert res.status_code == 409
        assert res.json()["error"]["detail"] == "Active company already exists"

        # 9. Founder updates company -> 200
        res = test_client.patch(
            "/api/companies/me",
            json={
                "name": "Hyperion Global",
                "country": "United Arab Emirates",
                "city": "Dubai",
                "country_code": "AE",
            },
            headers=founder_h,
        )
        assert res.status_code == 200
        assert res.json()["name"] == "Hyperion Global"
        assert res.json()["city"] == "Dubai"
        assert res.json()["country_code"] == "AE"

        # 10. Founder soft deletes company -> 204
        res = test_client.delete("/api/companies", headers=founder_h)
        assert res.status_code == 204

        # 11. Founder reading company after delete -> 200 null
        res = test_client.get("/api/companies/me", headers=founder_h)
        assert res.status_code == 200
        assert res.json() is None

        # 12. Revoked token test: bumping token_version invalidates the token
        sql(
            "UPDATE users SET token_version = token_version + 1 WHERE email = 'founder@example.com'"
        )
        res = test_client.get("/api/companies/me", headers=founder_h)
        assert res.status_code == 401
        assert res.json()["error"]["detail"] == "Invalid or expired token"
