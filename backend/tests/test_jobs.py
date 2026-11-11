"""Unit and PostgreSQL/PostGIS integration tests for jobs CRUD (BE-25)."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import security
from app.auth.deps import get_current_user, get_current_user_optional
from app.companies.models import Company
from app.users.models import User

AUTH_SECRET = "test-only-jwt-secret-0123456789abcdef"

OWNER_USER = User(
    id=10,
    email="employer@example.com",
    status="active",
    token_version=1,
    is_email_verified=True,
)
OTHER_USER = User(
    id=20,
    email="seeker@example.com",
    status="active",
    token_version=1,
    is_email_verified=True,
)

OWNER_TOKEN, _ = security.create_token(
    secret=AUTH_SECRET,
    user_id=OWNER_USER.id,
    scope="access",
    lifetime=timedelta(minutes=15),
    ver=1,
)
AUTH_HEADER = {"Authorization": f"Bearer {OWNER_TOKEN}"}


def _job_payload(**overrides) -> dict:
    base = {
        "title": "Backend Engineer",
        "description": "Build FastAPI and PostgreSQL services.",
        "latitude": 24.4539,
        "longitude": 54.3773,
        "location": "Abu Dhabi, UAE",
        "status": "draft",
        "salary_amount": "15000.00",
        "salary_type": "monthly",
        "salary_currency": "AED",
        "schedule": "full_time",
        "urgency": "normal",
    }
    base.update(overrides)
    return base


def _fake_company(owner_user_id: int = 10, company_id: int = 5, name: str = "WOZU Labs") -> Company:
    return Company(id=company_id, owner_user_id=owner_user_id, name=name, status="active")


def _fake_job_detail(
    *,
    job_id: int = 101,
    owner_id: int = 5,
    owner_user_id: int = 10,
    status_val: str = "open",
    views_count: int = 7,
    applications_count: int = 3,
    new_applications_count: int = 2,
) -> dict:
    now = datetime.now(UTC)
    return {
        "id": job_id,
        "owner_id": owner_id,
        "company_name": "WOZU Labs",
        "company_owner_user_id": owner_user_id,
        "title": "Backend Engineer",
        "description": "Build FastAPI and PostgreSQL services.",
        "status": status_val,
        "latitude": 24.4539,
        "longitude": 54.3773,
        "location": "Abu Dhabi, UAE",
        "salary_amount": Decimal("15000.00"),
        "salary_type": "monthly",
        "salary_currency": "AED",
        "schedule": "full_time",
        "urgency": "normal",
        "views_count": views_count,
        "applications_count": applications_count,
        "new_applications_count": new_applications_count,
        "created_by_id": owner_user_id,
        "updated_by_id": owner_user_id,
        "created_at": now,
        "updated_at": now,
    }


# ── Fast Unit / Route Tests (No DB required) ───────────────────────────────────


def test_protected_job_endpoints_require_auth(client):
    """Creating, listing mine, patching, or deleting a job requires Bearer auth."""
    for method, path, kwargs in [
        ("POST", "/api/jobs", {"json": _job_payload()}),
        ("GET", "/api/jobs/mine", {}),
        ("PATCH", "/api/jobs/1", {"json": {"title": "Updated"}}),
        ("DELETE", "/api/jobs/1", {}),
    ]:
        res = getattr(client, method.lower())(path, **kwargs)
        assert res.status_code == 401
        assert res.json()["error"]["detail"] == "Not authenticated"


def test_invalid_bearer_tokens_rejected_even_on_optional_route(client):
    """Numeric bearer bypass, expired tokens, and refresh tokens all fail with 401."""
    expired, _ = security.create_token(
        secret=AUTH_SECRET,
        user_id=10,
        scope="access",
        lifetime=timedelta(seconds=-5),
        ver=1,
    )
    refresh, _ = security.create_token(
        secret=AUTH_SECRET,
        user_id=10,
        scope="refresh",
        lifetime=timedelta(days=1),
        ver=1,
    )
    for token in ("42", expired, refresh):
        headers = {"Authorization": f"Bearer {token}"}
        for method, path in [
            ("GET", "/api/jobs/mine"),
            ("GET", "/api/jobs/1"),
        ]:
            res = getattr(client, method.lower())(path, headers=headers)
            assert res.status_code == 401
            assert res.json()["error"]["detail"] == "Invalid or expired token"


def test_create_job_requires_active_company(client):
    """POST /api/jobs returns 404 when the caller has no active company."""
    client.app.dependency_overrides[get_current_user] = lambda: OWNER_USER
    with patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_comp:
        mock_comp.return_value = None
        res = client.post("/api/jobs", json=_job_payload(), headers=AUTH_HEADER)
    assert res.status_code == 404
    assert res.json()["error"]["detail"] == "Active company not found"


def test_create_job_success_and_defaults(client):
    """POST /api/jobs creates a draft job by default and returns 201 JobOut."""
    from app.jobs.models import Job

    client.app.dependency_overrides[get_current_user] = lambda: OWNER_USER
    company = _fake_company()
    now = datetime.now(UTC)
    created_job = Job(
        id=55,
        owner_id=company.id,
        title="Backend Engineer",
        description="Build FastAPI and PostgreSQL services.",
        status="draft",
        latitude=24.4539,
        longitude=54.3773,
        location="Abu Dhabi, UAE",
        salary_amount=Decimal("15000.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="full_time",
        urgency="normal",
        created_by_id=OWNER_USER.id,
        updated_by_id=OWNER_USER.id,
    )
    created_job.created_at = now
    created_job.updated_at = now

    payload = _job_payload()
    del payload["status"]

    with (
        patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_comp,
        patch("app.jobs.repo.create_job", new_callable=AsyncMock) as mock_create,
    ):
        mock_comp.return_value = company
        mock_create.return_value = created_job
        res = client.post("/api/jobs", json=payload, headers=AUTH_HEADER)

    assert res.status_code == 201
    assert mock_create.call_args.kwargs["values"]["status"] == "draft"
    body = res.json()
    assert body["id"] == 55
    assert body["company_name"] == "WOZU Labs"
    assert body["status"] == "draft"
    assert body["views_count"] == 0


@pytest.mark.parametrize(
    "bad_fields",
    [
        {"status": "active"},  # legacy reference status removed in BE-25
        {"status": "deleted"},
        {"latitude": 90.01},
        {"latitude": -90.01},
        {"longitude": 180.01},
        {"longitude": -180.01},
        {"salary_amount": -1},
        {"salary_currency": "usd"},
        {"salary_currency": "US"},
        {"salary_currency": "12A"},
        {"title": "   "},
    ],
)
def test_create_job_validation_rejects_invalid_constraints(client, bad_fields):
    """Constraint violations and legacy 'active' status fail cleanly with 422."""
    client.app.dependency_overrides[get_current_user] = lambda: OWNER_USER
    res = client.post("/api/jobs", json=_job_payload(**bad_fields), headers=AUTH_HEADER)
    assert res.status_code == 422


def test_list_my_jobs_requires_active_company(client):
    """GET /api/jobs/mine returns 404 if the user owns no active company."""
    client.app.dependency_overrides[get_current_user] = lambda: OWNER_USER
    with patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_comp:
        mock_comp.return_value = None
        res = client.get("/api/jobs/mine", headers=AUTH_HEADER)
    assert res.status_code == 404


def test_list_my_jobs_returns_counters(client):
    """GET /api/jobs/mine returns owned jobs with view and application counters."""
    client.app.dependency_overrides[get_current_user] = lambda: OWNER_USER
    company = _fake_company()
    rows = [_fake_job_detail(job_id=101, status_val="draft", views_count=4, applications_count=2)]

    with (
        patch("app.companies.repo.get_active_by_owner_id", new_callable=AsyncMock) as mock_comp,
        patch("app.jobs.repo.list_company_jobs", new_callable=AsyncMock) as mock_list,
    ):
        mock_comp.return_value = company
        mock_list.return_value = rows
        res = client.get("/api/jobs/mine", headers=AUTH_HEADER)

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["company_name"] == "WOZU Labs"
    assert body[0]["status"] == "draft"
    assert body[0]["views_count"] == 4
    assert body[0]["applications_count"] == 2
    assert body[0]["new_applications_count"] == 2


def test_get_job_visibility_by_status_and_owner(client):
    """Draft jobs are 404 to non-owners and 200 to the owner; open jobs are public."""
    # Real get_current_user_optional path with no Authorization header sees open job
    with patch("app.jobs.repo.get_job_detail", new_callable=AsyncMock) as mock_detail:
        mock_detail.return_value = _fake_job_detail(status_val="open", new_applications_count=5)
        res = client.get("/api/jobs/101")
    assert res.status_code == 200
    assert res.json()["status"] == "open"
    assert res.json()["new_applications_count"] == 0

    # Real get_current_user_optional path with no header cannot view draft job
    with patch("app.jobs.repo.get_job_detail", new_callable=AsyncMock) as mock_detail:
        mock_detail.return_value = _fake_job_detail(status_val="draft")
        res = client.get("/api/jobs/101")
    assert res.status_code == 404

    # Another logged-in user cannot view draft job
    client.app.dependency_overrides[get_current_user_optional] = lambda: OTHER_USER
    with patch("app.jobs.repo.get_job_detail", new_callable=AsyncMock) as mock_detail:
        mock_detail.return_value = _fake_job_detail(status_val="draft")
        res = client.get("/api/jobs/101", headers=AUTH_HEADER)
    assert res.status_code == 404

    # Owner CAN view draft job with real counters
    client.app.dependency_overrides[get_current_user_optional] = lambda: OWNER_USER
    with patch("app.jobs.repo.get_job_detail", new_callable=AsyncMock) as mock_detail:
        mock_detail.return_value = _fake_job_detail(status_val="draft", new_applications_count=5)
        res = client.get("/api/jobs/101", headers=AUTH_HEADER)
    assert res.status_code == 200
    assert res.json()["status"] == "draft"
    assert res.json()["new_applications_count"] == 5


def test_patch_job_validation_and_ownership(client):
    """PATCH rejects unknown/null non-nullable fields (422) and non-owned jobs (404)."""
    client.app.dependency_overrides[get_current_user] = lambda: OWNER_USER

    for bad_patch in [
        {"unknown_field": 1},
        {"title": None},
        {"status": "active"},
        {"status": "deleted"},
        {"latitude": -91},
    ]:
        res = client.patch("/api/jobs/101", json=bad_patch, headers=AUTH_HEADER)
        assert res.status_code == 422

    with patch("app.jobs.repo.get_owned_job", new_callable=AsyncMock) as mock_owned:
        mock_owned.return_value = None
        res = client.patch("/api/jobs/101", json={"title": "Updated"}, headers=AUTH_HEADER)
    assert res.status_code == 404

    with (
        patch("app.jobs.repo.get_owned_job", new_callable=AsyncMock) as mock_owned,
        patch("app.jobs.repo.update_job", new_callable=AsyncMock) as mock_upd,
        patch("app.jobs.repo.get_job_detail", new_callable=AsyncMock) as mock_detail,
    ):
        mock_owned.return_value = object()
        detail = _fake_job_detail(status_val="open", views_count=9)
        detail["salary_amount"] = None
        detail["salary_currency"] = None
        mock_detail.return_value = detail
        res = client.patch(
            "/api/jobs/101",
            json={"status": "open", "salary_amount": None, "salary_currency": None},
            headers=AUTH_HEADER,
        )

    assert res.status_code == 200
    assert mock_upd.call_args.kwargs["values"] == {
        "status": "open",
        "salary_amount": None,
        "salary_currency": None,
    }
    assert res.json()["status"] == "open"
    assert res.json()["salary_amount"] is None
    assert res.json()["views_count"] == 9


def test_delete_job_ownership_and_success(client):
    """DELETE returns 404 when not owned/missing and 204 when soft-deleted by owner."""
    client.app.dependency_overrides[get_current_user] = lambda: OWNER_USER
    with patch("app.jobs.repo.get_owned_job", new_callable=AsyncMock) as mock_owned:
        mock_owned.return_value = None
        res = client.delete("/api/jobs/101", headers=AUTH_HEADER)
    assert res.status_code == 404

    with (
        patch("app.jobs.repo.get_owned_job", new_callable=AsyncMock) as mock_owned,
        patch("app.jobs.repo.soft_delete_job", new_callable=AsyncMock) as mock_del,
    ):
        mock_owned.return_value = object()
        res = client.delete("/api/jobs/101", headers=AUTH_HEADER)
    assert res.status_code == 204
    mock_del.assert_awaited_once()


def test_openapi_documents_jobs_routes_and_draft_status(client):
    """OpenAPI documents BE-25 routes and 'draft'/'open' statuses (not 'active')."""
    spec = client.get("/api/openapi.json").json()
    for path in ("/api/jobs", "/api/jobs/mine", "/api/jobs/{job_id}"):
        assert path in spec["paths"]
    status_schema = spec["components"]["schemas"]["JobCreate"]["properties"]["status"]
    assert status_schema["default"] == "draft"
    assert status_schema["enum"] == ["draft", "open"]


# ── Real PostgreSQL + PostGIS Tests ────────────────────────────────────────────

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)


def _seed_db_user(email: str) -> int:
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified, status, token_version,"
        " first_name, last_name, position, birth_date, bio)"
        " VALUES (:email, :password_hash, true, 'active', 1,"
        " 'Test', 'User', 'Dev', '1995-01-01', 'Bio')",
        email=email,
        password_hash=PASSWORD_HASH,
    )
    rows = sql("SELECT id FROM users WHERE email = :email", email=email)
    return int(rows[0][0])


@needs_database
def test_jobs_crud_postgis_counters_and_visibility_on_postgres():
    """Real PostgreSQL+PostGIS lifecycle: CRUD, visibility, counters, PostGIS location_point."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, companies, jobs, applications, job_views RESTART IDENTITY CASCADE")

    employer_id = _seed_db_user("employer@example.com")
    other_id = _seed_db_user("applicant@example.com")

    with TestClient(build_app(database_url=TEST_DATABASE_URL)) as test_client:
        emp_tok = test_client.post(
            "/api/auth/login",
            json={"email": "employer@example.com", "password": PASSWORD},
        ).json()["access_token"]
        other_tok = test_client.post(
            "/api/auth/login",
            json={"email": "applicant@example.com", "password": PASSWORD},
        ).json()["access_token"]
        emp_h = {"Authorization": f"Bearer {emp_tok}"}
        other_h = {"Authorization": f"Bearer {other_tok}"}

        # 1. Without a company, POST /jobs and GET /jobs/mine both return 404
        assert test_client.post("/api/jobs", json=_job_payload(), headers=emp_h).status_code == 404
        assert test_client.get("/api/jobs/mine", headers=emp_h).status_code == 404

        # 2. Register employer company
        comp_res = test_client.post(
            "/api/companies",
            json={"name": "Abu Dhabi Robotics", "country": "UAE", "city": "Abu Dhabi"},
            headers=emp_h,
        )
        assert comp_res.status_code == 201
        company_id = comp_res.json()["id"]

        # 3. Create draft job (status omitted -> defaults to "draft")
        draft_payload = _job_payload()
        del draft_payload["status"]
        create_res = test_client.post("/api/jobs", json=draft_payload, headers=emp_h)
        assert create_res.status_code == 201
        job = create_res.json()
        job_id = job["id"]
        assert job["status"] == "draft"
        assert job["owner_id"] == company_id
        assert job["company_name"] == "Abu Dhabi Robotics"
        assert job["created_by_id"] == employer_id
        assert job["updated_by_id"] == employer_id

        # 4. Verify PostGIS computed geography(Point, 4326) and search_vector trigger
        geo_rows = sql(
            "SELECT ST_X(location_point::geometry), ST_Y(location_point::geometry), "
            "search_vector IS NOT NULL FROM jobs WHERE id = :id",
            id=job_id,
        )
        lng_db, lat_db, has_vector = geo_rows[0]
        assert abs(lng_db - 54.3773) < 1e-6
        assert abs(lat_db - 24.4539) < 1e-6
        assert has_vector is True

        # 5. Non-open job is hidden from anonymous and other users (404), visible to owner
        assert test_client.get(f"/api/jobs/{job_id}").status_code == 404
        assert test_client.get(f"/api/jobs/{job_id}", headers=other_h).status_code == 404
        assert test_client.get(f"/api/jobs/{job_id}", headers=emp_h).status_code == 200

        # 6. Non-owner cannot PATCH or DELETE (404)
        assert (
            test_client.patch(
                f"/api/jobs/{job_id}", json={"title": "Hijacked"}, headers=other_h
            ).status_code
            == 404
        )
        assert test_client.delete(f"/api/jobs/{job_id}", headers=other_h).status_code == 404

        # 7. Partial PATCH updates coordinates, clears nullable salary, and publishes ("open")
        patch_res = test_client.patch(
            f"/api/jobs/{job_id}",
            json={
                "status": "open",
                "latitude": 25.2048,
                "longitude": 55.2708,
                "location": "Dubai, UAE",
                "salary_amount": None,
                "salary_currency": None,
            },
            headers=emp_h,
        )
        assert patch_res.status_code == 200
        patched = patch_res.json()
        assert patched["status"] == "open"
        assert patched["location"] == "Dubai, UAE"
        assert patched["salary_amount"] is None
        assert patched["salary_currency"] is None

        geo_updated = sql(
            "SELECT ST_X(location_point::geometry), ST_Y(location_point::geometry) "
            "FROM jobs WHERE id = :id",
            id=job_id,
        )
        assert abs(geo_updated[0][0] - 55.2708) < 1e-6
        assert abs(geo_updated[0][1] - 25.2048) < 1e-6

        # 8. Open job is now visible anonymously and to other users
        assert test_client.get(f"/api/jobs/{job_id}").status_code == 200
        assert test_client.get(f"/api/jobs/{job_id}", headers=other_h).status_code == 200

        # 9. Counters on GET /api/jobs/mine & GET /api/jobs/{id}
        sql(
            "INSERT INTO job_views (job_id, viewer_id) VALUES (:jid, :uid), (:jid, NULL)",
            jid=job_id,
            uid=other_id,
        )
        sql(
            "INSERT INTO applications (job_id, applicant_id, company_id, status) "
            "VALUES (:jid, :u1, :cid, 'submitted'), (:jid, :u2, :cid, 'withdrawn')",
            jid=job_id,
            u1=other_id,
            u2=employer_id,
            cid=company_id,
        )
        mine_res = test_client.get("/api/jobs/mine", headers=emp_h)
        assert mine_res.status_code == 200
        mine_items = mine_res.json()
        assert len(mine_items) == 1
        assert mine_items[0]["views_count"] == 2
        assert mine_items[0]["applications_count"] == 1
        assert mine_items[0]["new_applications_count"] == 1

        # Public view hides new_applications_count while returning job details
        pub_res = test_client.get(f"/api/jobs/{job_id}")
        assert pub_res.status_code == 200
        assert pub_res.json()["new_applications_count"] == 0

        # 10. Soft delete hides job from /mine, GET, PATCH, DELETE
        del_res = test_client.delete(f"/api/jobs/{job_id}", headers=emp_h)
        assert del_res.status_code == 204
        assert test_client.get("/api/jobs/mine", headers=emp_h).json() == []
        assert test_client.get(f"/api/jobs/{job_id}", headers=emp_h).status_code == 404
        assert test_client.delete(f"/api/jobs/{job_id}", headers=emp_h).status_code == 404


@needs_database
def test_jobs_database_check_constraints_enforced():
    """PostgreSQL CHECK constraints reject out-of-range coords, negative salary, bad currency."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, companies, jobs RESTART IDENTITY CASCADE")
    owner_id = _seed_db_user("constraint@example.com")
    sql(
        "INSERT INTO companies (owner_user_id, name, status) VALUES (:uid, 'Co', 'active')",
        uid=owner_id,
    )
    company_id = int(sql("SELECT id FROM companies WHERE owner_user_id = :uid", uid=owner_id)[0][0])

    async def _assert_constraints() -> None:
        engine = create_async_engine(TEST_DATABASE_URL)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                bad_cases = [
                    (95.0, 54.0, "100.00", "AED", "latitude_range"),
                    (24.0, 185.0, "100.00", "AED", "longitude_range"),
                    (24.0, 54.0, "-5.00", "AED", "salary_not_negative"),
                    (24.0, 54.0, "100.00", "usd", "currency_iso_4217"),
                ]
                for lat, lng, sal, cur, constraint in bad_cases:
                    with pytest.raises(IntegrityError) as exc_info:
                        async with session.begin_nested():
                            await session.execute(
                                text(
                                    "INSERT INTO jobs (owner_id, title, description, status,"
                                    " latitude, longitude, location, salary_amount,"
                                    " salary_currency) VALUES (:cid, 'Dev', 'Desc', 'draft',"
                                    " :lat, :lng, 'City', :sal, :cur)"
                                ),
                                {
                                    "cid": company_id,
                                    "lat": lat,
                                    "lng": lng,
                                    "sal": Decimal(sal),
                                    "cur": cur,
                                },
                            )
                    assert constraint in str(exc_info.value)
        finally:
            await engine.dispose()

    asyncio.run(_assert_constraints())
