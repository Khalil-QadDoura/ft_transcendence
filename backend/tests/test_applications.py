"""Unit, PostgreSQL, Redis, and WebSocket integration tests for applications (BE-28)."""

import asyncio
import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx2
import pytest
import redis
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
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from websockets.sync.client import connect as ws_connect

from app.applications.constants import (
    APPLICANT_TRANSITIONS,
    EMPLOYER_TRANSITIONS,
    EVENT_APPLICATION_CREATED,
    EVENT_APPLICATION_UPDATED,
    MAX_ID,
)
from app.applications.models import APPLICATION_STATUSES, Application
from app.auth import security
from app.auth.deps import get_current_user, get_current_user_optional
from app.companies.models import Company
from app.core.redis_client import get_redis
from app.jobs.models import Job
from app.users.models import User

AUTH_SECRET = "test-only-jwt-secret-0123456789abcdef"

EMPLOYER_USER = User(
    id=10,
    email="employer@example.com",
    status="active",
    token_version=1,
    is_email_verified=True,
    first_name="Elena",
    last_name="Boss",
    position="Hiring Manager",
)
APPLICANT_USER = User(
    id=20,
    email="applicant@example.com",
    status="active",
    token_version=1,
    is_email_verified=True,
    first_name="Sam",
    last_name="Seeker",
    position="Backend Developer",
)
INCOMPLETE_USER = User(
    id=21,
    email="incomplete@example.com",
    status="active",
    token_version=1,
    is_email_verified=True,
    first_name="OnlyFirst",
    last_name="   ",
    position=None,
)
STRANGER_USER = User(
    id=30,
    email="stranger@example.com",
    status="active",
    token_version=1,
    is_email_verified=True,
    first_name="Other",
    last_name="Person",
    position="Designer",
)

EMPLOYER_TOKEN, _ = security.create_token(
    AUTH_SECRET, user_id=EMPLOYER_USER.id, scope="access", lifetime=timedelta(minutes=15), ver=1
)
APPLICANT_TOKEN, _ = security.create_token(
    AUTH_SECRET, user_id=APPLICANT_USER.id, scope="access", lifetime=timedelta(minutes=15), ver=1
)
EMPLOYER_HEADER = {"Authorization": f"Bearer {EMPLOYER_TOKEN}"}
APPLICANT_HEADER = {"Authorization": f"Bearer {APPLICANT_TOKEN}"}


def _fake_company(owner_user_id: int = 10, company_id: int = 5) -> Company:
    return Company(id=company_id, owner_user_id=owner_user_id, name="WOZU Labs", status="active")


def _fake_job(job_id: int = 101, owner_id: int = 5, status_val: str = "open") -> Job:
    return Job(
        id=job_id,
        owner_id=owner_id,
        title="Backend Engineer",
        description="Build FastAPI APIs",
        status=status_val,
        latitude=24.4539,
        longitude=54.3773,
        location="Abu Dhabi",
        salary_type="monthly",
        schedule="full_time",
        urgency="normal",
    )


def _fake_detail(
    *,
    app_id: int = 77,
    job_id: int = 101,
    applicant_id: int = 20,
    company_id: int = 5,
    owner_user_id: int = 10,
    company_status: str = "active",
    app_status: str = "submitted",
    cover_note: str | None = "Excited to join!",
    conversation_id: int | None = None,
    viewed_at: datetime | None = None,
) -> dict:
    now = datetime.now(UTC)
    app = Application(
        id=app_id,
        job_id=job_id,
        applicant_id=applicant_id,
        company_id=company_id,
        intro_video_id=501,
        status=app_status,
        cover_note=cover_note,
        conversation_id=conversation_id,
        applied_at=now,
        viewed_at=viewed_at,
    )
    app.created_at = now
    app.updated_at = now
    return {
        "application": app,
        "job_title": "Backend Engineer",
        "company_name": "WOZU Labs",
        "company_owner_user_id": owner_user_id,
        "company_status": company_status,
        "applicant_first_name": "Sam",
        "applicant_last_name": "Seeker",
        "applicant_position": "Backend Developer",
        "applicant_avatar_key": "avatars/20/pic.png",
        "video_object_key": "users/20/intro/abc.mp4",
        "video_lifecycle_status": "posted",
    }


# ── Fast Unit / Route / Validation Tests (No DB required) ──────────────────────


def test_protected_application_endpoints_require_auth(client):
    """All protected application routes reject unauthenticated callers with 401."""
    for method, path, kwargs in [
        ("POST", "/api/jobs/1/apply", {"json": {}}),
        ("GET", "/api/jobs/1/applications", {}),
        ("GET", "/api/applications/mine", {}),
        ("GET", "/api/applications/1", {}),
        ("DELETE", "/api/applications/1", {}),
        ("PATCH", "/api/applications/1/status", {"json": {"status": "viewed"}}),
    ]:
        res = getattr(client, method.lower())(path, **kwargs)
        assert res.status_code == 401
        assert res.json()["error"]["detail"] == "Not authenticated"


def test_invalid_bearer_token_rejected_on_optional_view_route(client):
    """POST /api/jobs/{id}/view rejects malformed Bearer tokens with 401."""
    res = client.post("/api/jobs/1/view", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
    assert res.json()["error"]["detail"] == "Invalid or expired token"


def test_application_input_validation_errors(client):
    """Out-of-range IDs, invalid status filters, oversized notes, and extra keys return 422."""
    client.app.dependency_overrides[get_current_user] = lambda: APPLICANT_USER
    assert client.post("/api/jobs/0/apply", json={}, headers=APPLICANT_HEADER).status_code == 422
    assert (
        client.post(f"/api/jobs/{MAX_ID + 1}/apply", json={}, headers=APPLICANT_HEADER).status_code
        == 422
    )
    assert (
        client.post(
            "/api/jobs/1/apply", json={"cover_note": "x" * 1001}, headers=APPLICANT_HEADER
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/jobs/1/apply", json={"unexpected": True}, headers=APPLICANT_HEADER
        ).status_code
        == 422
    )
    assert (
        client.get("/api/applications/mine?status=bogus", headers=APPLICANT_HEADER).status_code
        == 422
    )
    assert (
        client.get("/api/applications/mine?limit=101", headers=APPLICANT_HEADER).status_code == 422
    )
    assert client.get("/api/applications/0", headers=APPLICANT_HEADER).status_code == 422
    assert (
        client.patch(
            "/api/applications/1/status",
            json={"status": "viewed", "note": "n" * 501},
            headers=APPLICANT_HEADER,
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/applications/1/status",
            json={"status": "invented"},
            headers=APPLICANT_HEADER,
        ).status_code
        == 422
    )


def test_apply_guards_unit(client):
    """Apply rejects draft/missing jobs (404), own job (403), duplicate (409), and guards (422)."""
    client.app.dependency_overrides[get_current_user] = lambda: APPLICANT_USER
    company = _fake_company(owner_user_id=10)
    draft_job = _fake_job(status_val="draft")
    open_job = _fake_job(status_val="open")

    # Missing job -> 404
    with patch("app.applications.repo.get_job_and_company", new_callable=AsyncMock) as m_job:
        m_job.return_value = None
        res = client.post("/api/jobs/101/apply", headers=APPLICANT_HEADER)
    assert res.status_code == 404

    # Draft job -> 404 (issue #10)
    with patch("app.applications.repo.get_job_and_company", new_callable=AsyncMock) as m_job:
        m_job.return_value = (draft_job, company)
        res = client.post("/api/jobs/101/apply", json={}, headers=APPLICANT_HEADER)
    assert res.status_code == 404

    # Own company job -> 403
    client.app.dependency_overrides[get_current_user] = lambda: EMPLOYER_USER
    with patch("app.applications.repo.get_job_and_company", new_callable=AsyncMock) as m_job:
        m_job.return_value = (open_job, company)
        res = client.post("/api/jobs/101/apply", json={}, headers=EMPLOYER_HEADER)
    assert res.status_code == 403

    # Duplicate -> 409
    client.app.dependency_overrides[get_current_user] = lambda: APPLICANT_USER
    with (
        patch("app.applications.repo.get_job_and_company", new_callable=AsyncMock) as m_job,
        patch(
            "app.applications.repo.get_application_by_job_and_user", new_callable=AsyncMock
        ) as m_dup,
    ):
        m_job.return_value = (open_job, company)
        m_dup.return_value = object()
        res = client.post("/api/jobs/101/apply", json={}, headers=APPLICANT_HEADER)
    assert res.status_code == 409

    # Incomplete profile -> 422 with profile_incomplete / next_step=profile
    client.app.dependency_overrides[get_current_user] = lambda: INCOMPLETE_USER
    with (
        patch("app.applications.repo.get_job_and_company", new_callable=AsyncMock) as m_job,
        patch(
            "app.applications.repo.get_application_by_job_and_user", new_callable=AsyncMock
        ) as m_dup,
    ):
        m_job.return_value = (open_job, company)
        m_dup.return_value = None
        res = client.post("/api/jobs/101/apply", json={}, headers=APPLICANT_HEADER)
    assert res.status_code == 422
    assert res.json()["error"]["detail"] == {"code": "profile_incomplete", "next_step": "profile"}

    # Complete profile, no posted approved video -> 422 with no_video / next_step=video
    client.app.dependency_overrides[get_current_user] = lambda: APPLICANT_USER
    with (
        patch("app.applications.repo.get_job_and_company", new_callable=AsyncMock) as m_job,
        patch(
            "app.applications.repo.get_application_by_job_and_user", new_callable=AsyncMock
        ) as m_dup,
        patch(
            "app.applications.repo.get_posted_approved_video_id", new_callable=AsyncMock
        ) as m_vid,
    ):
        m_job.return_value = (open_job, company)
        m_dup.return_value = None
        m_vid.return_value = None
        res = client.post("/api/jobs/101/apply", json={}, headers=APPLICANT_HEADER)
    assert res.status_code == 422
    assert res.json()["error"]["detail"] == {"code": "no_video", "next_step": "video"}


@pytest.mark.parametrize(
    ("from_status", "to_status", "allowed"),
    [
        (src, dst, dst in EMPLOYER_TRANSITIONS.get(src, ()))
        for src in APPLICATION_STATUSES
        for dst in APPLICATION_STATUSES
    ],
)
def test_employer_transition_matrix(client, from_status, to_status, allowed):
    """Every (from_status, to_status) employer pair either succeeds (200) or fails (409)."""
    client.app.dependency_overrides[get_current_user] = lambda: EMPLOYER_USER
    before = _fake_detail(app_status=from_status)
    after = _fake_detail(
        app_status=to_status,
        conversation_id=900 if to_status == "contacted" else None,
        viewed_at=datetime.now(UTC) if to_status == "viewed" else None,
    )

    with (
        patch("app.applications.repo.get_application_detail", new_callable=AsyncMock) as m_get,
        patch("app.applications.repo.update_status_if_matches", new_callable=AsyncMock) as m_upd,
        patch("app.applications.repo.log_event", new_callable=AsyncMock) as m_log,
        patch(
            "app.applications.service._ensure_contact_conversation_in_tx",
            new_callable=AsyncMock,
        ) as m_conv,
        patch("app.realtime.service.send_to_user", new_callable=AsyncMock) as m_ws,
    ):
        m_get.side_effect = [before, after]
        m_upd.return_value = after["application"]
        m_conv.return_value = 900
        res = client.patch(
            "/api/applications/77/status",
            json={"status": to_status},
            headers=EMPLOYER_HEADER,
        )

    if allowed:
        assert res.status_code == 200
        assert res.json()["status"] == to_status
        m_log.assert_awaited_once()
        m_ws.assert_awaited_once()
        assert m_ws.call_args.args[1] == APPLICANT_USER.id
        assert m_ws.call_args.args[2] == EVENT_APPLICATION_UPDATED
    else:
        assert res.status_code == 409
        m_upd.assert_not_awaited()
        m_ws.assert_not_awaited()


@pytest.mark.parametrize("from_status", APPLICATION_STATUSES)
def test_applicant_withdraw_matrix(client, from_status):
    """Candidates can withdraw active applications (204) and get 409 on terminal statuses."""
    client.app.dependency_overrides[get_current_user] = lambda: APPLICANT_USER
    before = _fake_detail(app_status=from_status)
    after = _fake_detail(app_status="withdrawn")
    allowed = "withdrawn" in APPLICANT_TRANSITIONS.get(from_status, ())

    with (
        patch("app.applications.repo.get_application_detail", new_callable=AsyncMock) as m_get,
        patch("app.applications.repo.update_status_if_matches", new_callable=AsyncMock) as m_upd,
        patch("app.applications.repo.log_event", new_callable=AsyncMock) as m_log,
        patch("app.realtime.service.send_to_user", new_callable=AsyncMock) as m_ws,
    ):
        m_get.side_effect = [before, after]
        m_upd.return_value = after["application"]
        res = client.delete("/api/applications/77", headers=APPLICANT_HEADER)

    if allowed:
        assert res.status_code == 204
        m_log.assert_awaited_once()
        m_ws.assert_awaited_once()
        assert m_ws.call_args.args[1] == EMPLOYER_USER.id
        assert m_ws.call_args.args[2] == EVENT_APPLICATION_UPDATED
    else:
        assert res.status_code == 409
        m_upd.assert_not_awaited()
        m_ws.assert_not_awaited()


def test_concurrent_transition_conflict_returns_409(client):
    """If another request changed the status before UPDATE, return 409 without WS push."""
    client.app.dependency_overrides[get_current_user] = lambda: EMPLOYER_USER
    with (
        patch("app.applications.repo.get_application_detail", new_callable=AsyncMock) as m_get,
        patch("app.applications.repo.update_status_if_matches", new_callable=AsyncMock) as m_upd,
        patch("app.realtime.service.send_to_user", new_callable=AsyncMock) as m_ws,
    ):
        m_get.return_value = _fake_detail(app_status="submitted")
        m_upd.return_value = None
        res = client.patch(
            "/api/applications/77/status",
            json={"status": "viewed"},
            headers=EMPLOYER_HEADER,
        )
    assert res.status_code == 409
    m_ws.assert_not_awaited()


def test_cross_user_access_controls_unit(client):
    """Strangers get 403 on read/list/status and 404 on withdraw; applicant cannot escalate."""
    detail = _fake_detail(applicant_id=APPLICANT_USER.id, owner_user_id=EMPLOYER_USER.id)
    company = _fake_company(owner_user_id=EMPLOYER_USER.id)
    job = _fake_job()

    # Stranger GET /applications/77 -> 403
    client.app.dependency_overrides[get_current_user] = lambda: STRANGER_USER
    with patch("app.applications.repo.get_application_detail", new_callable=AsyncMock) as m_get:
        m_get.return_value = detail
        assert client.get("/api/applications/77", headers=APPLICANT_HEADER).status_code == 403
        assert client.delete("/api/applications/77", headers=APPLICANT_HEADER).status_code == 404
        assert (
            client.patch(
                "/api/applications/77/status",
                json={"status": "viewed"},
                headers=APPLICANT_HEADER,
            ).status_code
            == 403
        )

    # Stranger GET /jobs/101/applications -> 403
    with patch("app.applications.repo.get_job_and_company", new_callable=AsyncMock) as m_job:
        m_job.return_value = (job, company)
        assert client.get("/api/jobs/101/applications", headers=APPLICANT_HEADER).status_code == 403

    # Applicant cannot PATCH own application status -> 403
    client.app.dependency_overrides[get_current_user] = lambda: APPLICANT_USER
    with patch("app.applications.repo.get_application_detail", new_callable=AsyncMock) as m_get:
        m_get.return_value = detail
        assert (
            client.patch(
                "/api/applications/77/status",
                json={"status": "hired"},
                headers=APPLICANT_HEADER,
            ).status_code
            == 403
        )


def test_record_view_handles_redis_outage_gracefully(client):
    """A Redis failure during view dedup still returns 204 instead of 500."""

    class BrokenRedis:
        async def set(self, *args, **kwargs):
            raise RedisError("redis down")

    client.app.dependency_overrides[get_current_user_optional] = lambda: None
    client.app.dependency_overrides[get_redis] = lambda: BrokenRedis()
    with (
        patch("app.applications.repo.get_job_and_company", new_callable=AsyncMock) as m_job,
        patch("app.applications.repo.record_view", new_callable=AsyncMock) as m_view,
    ):
        m_job.return_value = (_fake_job(status_val="open"), _fake_company())
        res = client.post("/api/jobs/101/view")
    assert res.status_code == 204
    m_view.assert_not_awaited()


def test_openapi_documents_applications_routes(client):
    """OpenAPI documents all 7 BE-28 routes and ApplicationOut fields."""
    spec = client.get("/api/openapi.json").json()
    for path in (
        "/api/jobs/{job_id}/apply",
        "/api/jobs/{job_id}/view",
        "/api/jobs/{job_id}/applications",
        "/api/applications/mine",
        "/api/applications/{app_id}",
        "/api/applications/{app_id}/status",
    ):
        assert path in spec["paths"]
    props = spec["components"]["schemas"]["ApplicationOut"]["properties"]
    for field in ("id", "job_id", "applicant_id", "status", "conversation_id", "intro_video_url"):
        assert field in props


# ── Real PostgreSQL + Redis + WebSocket Integration Tests ──────────────────────

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)


def _seed_user(
    email: str,
    *,
    first_name: str | None = "Test",
    last_name: str | None = "User",
    position: str | None = "Engineer",
) -> int:
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified, status, token_version,"
        " first_name, last_name, position, birth_date, bio)"
        " VALUES (:email, :password_hash, true, 'active', 1,"
        " :first_name, :last_name, :position, '1995-01-01', 'Bio')",
        email=email,
        password_hash=PASSWORD_HASH,
        first_name=first_name,
        last_name=last_name,
        position=position,
    )
    return int(sql("SELECT id FROM users WHERE email = :email", email=email)[0][0])


def _seed_video(
    user_id: int,
    *,
    object_key: str,
    moderation_status: str = "approved",
    lifecycle_status: str = "posted",
) -> int:
    sql(
        "INSERT INTO intro_videos (user_id, object_key, duration_sec, size_bytes, content_type,"
        " moderation_status, lifecycle_status)"
        " VALUES (:uid, :key, 20, 1024, 'video/mp4', :mod, :life)",
        uid=user_id,
        key=object_key,
        mod=moderation_status,
        life=lifecycle_status,
    )
    return int(sql("SELECT id FROM intro_videos WHERE object_key = :key", key=object_key)[0][0])


def _clear_view_keys() -> None:
    if TEST_REDIS_URL:
        with redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True) as r:
            keys = r.keys("job:view:*")
            if keys:
                r.delete(*keys)


def _login_header(test_client: TestClient, email: str) -> dict[str, str]:
    tok = test_client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def _create_company_and_job(
    test_client: TestClient,
    emp_h: dict[str, str],
    *,
    company_name: str = "WOZU Hiring Co",
    title: str = "Senior Backend Engineer",
    job_status: str = "open",
) -> int:
    if test_client.get("/api/companies/me", headers=emp_h).json() is None:
        comp = test_client.post(
            "/api/companies",
            json={"name": company_name, "country": "UAE", "city": "Abu Dhabi"},
            headers=emp_h,
        )
        assert comp.status_code == 201
    res = test_client.post(
        "/api/jobs",
        json={
            "title": title,
            "description": "Own APIs and data systems.",
            "latitude": 24.4539,
            "longitude": 54.3773,
            "location": "Abu Dhabi, UAE",
            "status": job_status,
            "salary_amount": "18000.00",
            "salary_type": "monthly",
            "salary_currency": "AED",
            "schedule": "full_time",
            "urgency": "urgent",
        },
        headers=emp_h,
    )
    assert res.status_code == 201
    return int(res.json()["id"])


@needs_database
@needs_redis
def test_applications_full_lifecycle_guards_events_and_views_on_postgres():
    """End-to-end DB + Redis check: guards, state machine, chat link, counters, pagination."""
    alembic("upgrade", "head")
    sql(
        "TRUNCATE users, companies, jobs, applications, application_events, job_views,"
        " intro_videos, conversations, conversation_participants, messages"
        " RESTART IDENTITY CASCADE"
    )
    _clear_view_keys()

    employer_id = _seed_user("emp@example.com", first_name="Boss", last_name="One", position="CTO")
    no_prof_id = _seed_user("noprof@example.com", first_name=None, last_name="X", position="Dev")
    no_vid_id = _seed_user("novid@example.com", first_name="No", last_name="Video", position="Dev")
    cand1_id = _seed_user("cand1@example.com", first_name="Alice", last_name="Dev", position="BE")
    cand2_id = _seed_user("cand2@example.com", first_name="Bob", last_name="Dev", position="FE")
    stranger_id = _seed_user("stranger@example.com")

    _seed_video(employer_id, object_key=f"users/{employer_id}/intro/emp.mp4")
    _seed_video(no_prof_id, object_key=f"users/{no_prof_id}/intro/np.mp4")
    # Pending (not approved) and unposted (not posted) videos must NOT satisfy the apply guard
    _seed_video(
        no_vid_id,
        object_key=f"users/{no_vid_id}/intro/pending.mp4",
        moderation_status="pending",
        lifecycle_status="loaded",
    )
    _seed_video(
        no_vid_id,
        object_key=f"users/{no_vid_id}/intro/unposted.mp4",
        moderation_status="approved",
        lifecycle_status="unposted",
    )
    cand1_vid = _seed_video(cand1_id, object_key=f"users/{cand1_id}/intro/c1.mp4")
    _seed_video(cand2_id, object_key=f"users/{cand2_id}/intro/c2.mp4")

    with TestClient(
        build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    ) as test_client:
        emp_h = _login_header(test_client, "emp@example.com")
        no_prof_h = _login_header(test_client, "noprof@example.com")
        no_vid_h = _login_header(test_client, "novid@example.com")
        cand1_h = _login_header(test_client, "cand1@example.com")
        cand2_h = _login_header(test_client, "cand2@example.com")
        stranger_h = _login_header(test_client, "stranger@example.com")

        draft_job_id = _create_company_and_job(
            test_client, emp_h, title="Draft", job_status="draft"
        )
        open_job_id = _create_company_and_job(
            test_client, emp_h, title="Backend", job_status="open"
        )
        open_job2_id = _create_company_and_job(test_client, emp_h, title="Staff", job_status="open")

        # 1. Draft job cannot be applied to (issue #10) and view is a 204 no-op
        assert (
            test_client.post(
                f"/api/jobs/{draft_job_id}/apply", json={}, headers=cand1_h
            ).status_code
            == 404
        )
        assert test_client.post(f"/api/jobs/{draft_job_id}/view", headers=emp_h).status_code == 204
        draft_views = sql("SELECT COUNT(*) FROM job_views WHERE job_id = :jid", jid=draft_job_id)
        assert draft_views[0][0] == 0

        # 2. Apply guards
        assert (
            test_client.post(f"/api/jobs/{open_job_id}/apply", json={}, headers=emp_h).status_code
            == 403
        )
        r_np = test_client.post(f"/api/jobs/{open_job_id}/apply", json={}, headers=no_prof_h)
        assert r_np.status_code == 422
        assert r_np.json()["error"]["detail"] == {
            "code": "profile_incomplete",
            "next_step": "profile",
        }
        r_nv = test_client.post(f"/api/jobs/{open_job_id}/apply", json={}, headers=no_vid_h)
        assert r_nv.status_code == 422
        assert r_nv.json()["error"]["detail"] == {"code": "no_video", "next_step": "video"}

        # 3. Job view deduplication per user per 24h + owner counter update
        assert test_client.post(f"/api/jobs/{open_job_id}/view", headers=cand1_h).status_code == 204
        assert test_client.post(f"/api/jobs/{open_job_id}/view", headers=cand1_h).status_code == 204
        assert test_client.post(f"/api/jobs/{open_job_id}/view", headers=cand2_h).status_code == 204
        assert test_client.post(f"/api/jobs/{open_job_id}/view").status_code == 204
        assert test_client.post(f"/api/jobs/{open_job_id}/view").status_code == 204
        assert sql("SELECT COUNT(*) FROM job_views WHERE job_id = :jid", jid=open_job_id)[0][0] == 3
        assert test_client.post("/api/jobs/999999/view", headers=cand1_h).status_code == 404

        # 4. Successful applications + duplicate 409
        r_app1 = test_client.post(
            f"/api/jobs/{open_job_id}/apply",
            json={"cover_note": "  Love this role!  "},
            headers=cand1_h,
        )
        assert r_app1.status_code == 201
        app1 = r_app1.json()
        app1_id = app1["id"]
        assert app1["status"] == "submitted"
        assert app1["cover_note"] == "Love this role!"
        assert app1["intro_video_id"] == cand1_vid
        assert app1["job_title"] == "Backend"
        assert app1["company_name"] == "WOZU Hiring Co"
        assert app1["applicant_first_name"] == "Alice"
        assert app1["intro_video_url"] is not None
        assert (
            test_client.post(f"/api/jobs/{open_job_id}/apply", json={}, headers=cand1_h).status_code
            == 409
        )

        app1_job2_id = test_client.post(f"/api/jobs/{open_job2_id}/apply", headers=cand1_h).json()[
            "id"
        ]
        app2_id = test_client.post(
            f"/api/jobs/{open_job_id}/apply", json={}, headers=cand2_h
        ).json()["id"]

        # 5. Owner job counters reflect views + applications + submitted (new) applications
        my_jobs = {j["id"]: j for j in test_client.get("/api/jobs/mine", headers=emp_h).json()}
        assert my_jobs[open_job_id]["views_count"] == 3
        assert my_jobs[open_job_id]["applications_count"] == 2
        assert my_jobs[open_job_id]["new_applications_count"] == 2

        # 6. Cross-user authorization checks
        assert (
            test_client.get(f"/api/applications/{app1_id}", headers=stranger_h).status_code == 403
        )
        assert (
            test_client.get(f"/api/jobs/{open_job_id}/applications", headers=cand1_h).status_code
            == 403
        )
        assert (
            test_client.patch(
                f"/api/applications/{app1_id}/status", json={"status": "hired"}, headers=cand1_h
            ).status_code
            == 403
        )
        assert (
            test_client.delete(f"/api/applications/{app1_id}", headers=stranger_h).status_code
            == 404
        )
        assert test_client.delete(f"/api/applications/{app1_id}", headers=emp_h).status_code == 404
        assert test_client.get(f"/api/applications/{app1_id}", headers=cand1_h).status_code == 200
        assert test_client.get(f"/api/applications/{app1_id}", headers=emp_h).status_code == 200

        # 7. Invalid jump rejected with 409
        assert (
            test_client.patch(
                f"/api/applications/{app1_id}/status", json={"status": "hired"}, headers=emp_h
            ).status_code
            == 409
        )

        # 8. Full employer progression: submitted -> viewed -> shortlisted -> contacted -> hired
        r_v = test_client.patch(
            f"/api/applications/{app1_id}/status",
            json={"status": "viewed", "note": "Reviewed video"},
            headers=emp_h,
        )
        assert r_v.status_code == 200
        assert r_v.json()["status"] == "viewed"
        assert r_v.json()["viewed_at"] is not None

        r_s = test_client.patch(
            f"/api/applications/{app1_id}/status",
            json={"status": "shortlisted"},
            headers=emp_h,
        )
        assert r_s.status_code == 200 and r_s.json()["status"] == "shortlisted"

        r_c = test_client.patch(
            f"/api/applications/{app1_id}/status",
            json={"status": "contacted", "note": "Let's chat"},
            headers=emp_h,
        )
        assert r_c.status_code == 200
        conv_id = r_c.json()["conversation_id"]
        assert conv_id is not None
        # Conversation is linked to application_id and accessible to both users
        conv_row = sql(
            "SELECT job_id, application_id FROM conversations WHERE id = :cid", cid=conv_id
        )[0]
        assert conv_row == (open_job_id, app1_id)
        assert test_client.get(f"/api/conversations/{conv_id}", headers=cand1_h).status_code == 200

        r_h = test_client.patch(
            f"/api/applications/{app1_id}/status",
            json={"status": "hired", "note": "Offer accepted"},
            headers=emp_h,
        )
        assert r_h.status_code == 200 and r_h.json()["status"] == "hired"

        # Terminal status cannot transition or be withdrawn
        assert (
            test_client.patch(
                f"/api/applications/{app1_id}/status", json={"status": "rejected"}, headers=emp_h
            ).status_code
            == 409
        )
        assert (
            test_client.delete(f"/api/applications/{app1_id}", headers=cand1_h).status_code == 409
        )

        # Audit trail has 5 ordered events: None->submitted, viewed, shortlisted, contacted, hired
        events = sql(
            "SELECT from_status::text, to_status::text, actor_id, note"
            " FROM application_events WHERE application_id = :aid ORDER BY id",
            aid=app1_id,
        )
        assert events == [
            (None, "submitted", cand1_id, None),
            ("submitted", "viewed", employer_id, "Reviewed video"),
            ("viewed", "shortlisted", employer_id, None),
            ("shortlisted", "contacted", employer_id, "Let's chat"),
            ("contacted", "hired", employer_id, "Offer accepted"),
        ]

        # 9. Candidate withdrawal updates status, logs event, and reduces job applications_count
        assert (
            test_client.delete(f"/api/applications/{app2_id}", headers=cand2_h).status_code == 204
        )
        assert (
            test_client.delete(f"/api/applications/{app2_id}", headers=cand2_h).status_code == 409
        )
        my_jobs_after = {
            j["id"]: j for j in test_client.get("/api/jobs/mine", headers=emp_h).json()
        }
        assert my_jobs_after[open_job_id]["applications_count"] == 1
        assert my_jobs_after[open_job_id]["new_applications_count"] == 0

        # 10. Cursor pagination & status filtering on /applications/mine and /jobs/{id}/applications
        p1 = test_client.get("/api/applications/mine?limit=1", headers=cand1_h).json()
        assert len(p1["items"]) == 1
        assert p1["items"][0]["id"] == app1_job2_id
        assert p1["next_cursor"] == app1_job2_id

        p2 = test_client.get(
            f"/api/applications/mine?limit=1&cursor={p1['next_cursor']}", headers=cand1_h
        ).json()
        assert len(p2["items"]) == 1
        assert p2["items"][0]["id"] == app1_id
        assert p2["next_cursor"] is None

        hired_only = test_client.get(
            f"/api/jobs/{open_job_id}/applications?status=hired", headers=emp_h
        ).json()
        assert [item["id"] for item in hired_only["items"]] == [app1_id]
        assert hired_only["next_cursor"] is None
        assert stranger_id > 0


@contextmanager
def _open_ws(base_http: str, auth_headers: dict[str, str]):
    ticket = httpx2.post(f"{base_http}/api/ws/ticket", headers=auth_headers).json()["ticket"]
    ws_url = base_http.replace("http://", "ws://") + f"/ws?ticket={ticket}"
    with ws_connect(ws_url, open_timeout=5) as ws:
        yield ws


def _wait_event(ws, expected_type: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"timed out waiting for WS event {expected_type!r}"
        frame = json.loads(ws.recv(timeout=remaining))
        if frame.get("type") == expected_type:
            return frame["payload"]


@needs_database
@needs_redis
def test_application_live_websocket_events():
    """Apply, status change, and withdraw push live WS events to the opposite party."""
    alembic("upgrade", "head")
    sql(
        "TRUNCATE users, companies, jobs, applications, application_events, intro_videos"
        " RESTART IDENTITY CASCADE"
    )
    _clear_view_keys()

    _seed_user("ws_emp@example.com", first_name="Emp", last_name="One", position="Lead")
    cand_id = _seed_user("ws_cand@example.com", first_name="Cand", last_name="One", position="Dev")
    _seed_video(cand_id, object_key=f"users/{cand_id}/intro/ws.mp4")

    app = build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    with running_server(app) as addr:
        base = f"http://{addr}"
        emp_tok = httpx2.post(
            f"{base}/api/auth/login",
            json={"email": "ws_emp@example.com", "password": PASSWORD},
        ).json()["access_token"]
        cand_tok = httpx2.post(
            f"{base}/api/auth/login",
            json={"email": "ws_cand@example.com", "password": PASSWORD},
        ).json()["access_token"]
        emp_h = {"Authorization": f"Bearer {emp_tok}"}
        cand_h = {"Authorization": f"Bearer {cand_tok}"}

        assert (
            httpx2.post(
                f"{base}/api/companies",
                json={"name": "Live Co", "country": "UAE", "city": "Abu Dhabi"},
                headers=emp_h,
            ).status_code
            == 201
        )
        job_id = httpx2.post(
            f"{base}/api/jobs",
            json={
                "title": "Realtime Engineer",
                "description": "WebSockets",
                "latitude": 24.4539,
                "longitude": 54.3773,
                "location": "Abu Dhabi",
                "status": "open",
            },
            headers=emp_h,
        ).json()["id"]

        with _open_ws(base, emp_h) as emp_ws, _open_ws(base, cand_h) as cand_ws:
            # 1. Candidate applies -> employer receives application_created
            r_apply = httpx2.post(f"{base}/api/jobs/{job_id}/apply", json={}, headers=cand_h)
            assert r_apply.status_code == 201
            app_id = r_apply.json()["id"]
            created_evt = _wait_event(emp_ws, EVENT_APPLICATION_CREATED)
            assert created_evt["id"] == app_id
            assert created_evt["status"] == "submitted"

            # 2. Employer marks viewed -> candidate receives application_updated
            r_upd = httpx2.patch(
                f"{base}/api/applications/{app_id}/status",
                json={"status": "viewed"},
                headers=emp_h,
            )
            assert r_upd.status_code == 200
            viewed_evt = _wait_event(cand_ws, EVENT_APPLICATION_UPDATED)
            assert viewed_evt["id"] == app_id
            assert viewed_evt["status"] == "viewed"

            # 3. Candidate withdraws -> employer receives application_updated
            r_wd = httpx2.delete(f"{base}/api/applications/{app_id}", headers=cand_h)
            assert r_wd.status_code == 204
            wd_evt = _wait_event(emp_ws, EVENT_APPLICATION_UPDATED)
            assert wd_evt["id"] == app_id
            assert wd_evt["status"] == "withdrawn"


@needs_database
@needs_redis
def test_concurrent_duplicate_apply_returns_one_201_and_one_409():
    """Two simultaneous apply calls for the same (job, applicant) produce one 201 and one 409."""
    alembic("upgrade", "head")
    sql(
        "TRUNCATE users, companies, jobs, applications, application_events, intro_videos"
        " RESTART IDENTITY CASCADE"
    )
    _seed_user("race_emp@example.com", first_name="Emp", last_name="Race", position="CTO")
    cand_id = _seed_user(
        "race_cand@example.com", first_name="Cand", last_name="Race", position="Dev"
    )
    _seed_video(cand_id, object_key=f"users/{cand_id}/intro/race.mp4")

    app = build_app(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL)
    with running_server(app) as addr:
        base = f"http://{addr}"
        emp_tok = httpx2.post(
            f"{base}/api/auth/login",
            json={"email": "race_emp@example.com", "password": PASSWORD},
        ).json()["access_token"]
        cand_tok = httpx2.post(
            f"{base}/api/auth/login",
            json={"email": "race_cand@example.com", "password": PASSWORD},
        ).json()["access_token"]
        emp_h = {"Authorization": f"Bearer {emp_tok}"}
        cand_h = {"Authorization": f"Bearer {cand_tok}"}

        httpx2.post(
            f"{base}/api/companies",
            json={"name": "Race Co", "country": "UAE", "city": "Abu Dhabi"},
            headers=emp_h,
        )
        job_id = httpx2.post(
            f"{base}/api/jobs",
            json={
                "title": "Concurrency Engineer",
                "description": "Locks",
                "latitude": 24.4539,
                "longitude": 54.3773,
                "location": "Abu Dhabi",
                "status": "open",
            },
            headers=emp_h,
        ).json()["id"]

        async def _burst() -> list[int]:
            async with httpx2.AsyncClient(base_url=base) as ac:
                r1, r2 = await asyncio.gather(
                    ac.post(f"/api/jobs/{job_id}/apply", json={}, headers=cand_h),
                    ac.post(f"/api/jobs/{job_id}/apply", json={}, headers=cand_h),
                )
                return sorted([r1.status_code, r2.status_code])

        assert asyncio.run(_burst()) == [201, 409]
        assert sql("SELECT COUNT(*) FROM applications WHERE job_id = :jid", jid=job_id)[0][0] == 1
