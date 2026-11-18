"""Unit and PostgreSQL/PostGIS integration tests for public job search (BE-26 / M6)."""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, sql
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import security
from app.jobs.repo import MAX_ID

PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)


# ── Fast Input Validation & Contract Tests (No DB required) ────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "lat=91&lng=54",
        "lat=-91&lng=54",
        "lat=24&lng=181",
        "lat=24&lng=-181",
        "lat=24",
        "lng=54",
        "radius_km=10",
        "lat=24&lng=54&radius_km=0",
        "lat=24&lng=54&radius_km=500.1",
        "sort_by=salary_magic",
        "schedule=freelance",
        "urgency=asap",
        "salary_min=-1",
        "salary_max=-10",
        "salary_min=5000&salary_max=1000",
        "limit=0",
        "limit=101",
        "cursor=0",
        f"cursor={MAX_ID + 1}",
    ],
)
def test_search_validation_rejects_bad_params_with_422(client, query):
    """Bad coordinates, partial geo pairs, unknown sort/enums, or invalid bounds return 422."""
    res = client.get(f"/api/jobs/open?{query}")
    assert res.status_code == 422


def test_openapi_documents_open_job_search_route(client):
    """OpenAPI documents GET /api/jobs/open, JobsPage, company_logo_url, and distance_km."""
    spec = client.get("/api/openapi.json").json()
    assert "/api/jobs/open" in spec["paths"]
    assert "JobsPage" in spec["components"]["schemas"]
    job_props = spec["components"]["schemas"]["JobOut"]["properties"]
    assert "company_logo_url" in job_props
    assert "distance_km" in job_props


# ── Real PostgreSQL + PostGIS Search, Sort, Cursor & EXPLAIN Tests ─────────────


def _seed_employer_and_company(
    email: str,
    *,
    company_name: str,
    logo_key: str | None = None,
    company_status: str = "active",
) -> int:
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified, status, token_version,"
        " first_name, last_name, position)"
        " VALUES (:email, :pw, true, 'active', 1, 'Emp', 'Search', 'Owner')",
        email=email,
        pw=PASSWORD_HASH,
    )
    user_id = int(sql("SELECT id FROM users WHERE email = :email", email=email)[0][0])
    sql(
        "INSERT INTO companies (owner_user_id, name, logo_object_key, status)"
        " VALUES (:uid, :name, :logo, :status)",
        uid=user_id,
        name=company_name,
        logo=logo_key,
        status=company_status,
    )
    return int(sql("SELECT id FROM companies WHERE owner_user_id = :uid", uid=user_id)[0][0])


def _seed_job(
    company_id: int,
    *,
    title: str,
    description: str,
    latitude: float,
    longitude: float,
    location: str = "Abu Dhabi, UAE",
    status: str = "open",
    salary_amount: str | None = "10000.00",
    salary_currency: str | None = "AED",
    schedule: str = "full_time",
    urgency: str = "normal",
) -> int:
    sql(
        "INSERT INTO jobs (owner_id, title, description, status, latitude, longitude, location,"
        " salary_amount, salary_type, salary_currency, schedule, urgency)"
        " VALUES (:cid, :title, :desc, :status, :lat, :lng, :loc,"
        " :sal, 'monthly', :cur, :sched, :urg)",
        cid=company_id,
        title=title,
        desc=description,
        status=status,
        lat=latitude,
        lng=longitude,
        loc=location,
        sal=salary_amount,
        cur=salary_currency,
        sched=schedule,
        urg=urgency,
    )
    return int(
        sql(
            "SELECT id FROM jobs WHERE owner_id = :cid AND title = :title ORDER BY id DESC LIMIT 1",
            cid=company_id,
            title=title,
        )[0][0]
    )


@needs_database
def test_job_search_filters_radius_fts_sort_and_cursor_pagination():
    """Real PostGIS search: visibility, radius boundary, FTS, filters, nearest & newest paging."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, companies, jobs RESTART IDENTITY CASCADE")

    active_co = _seed_employer_and_company(
        "co_active@example.com",
        company_name="Abu Dhabi Labs",
        logo_key="logos/1/brand.png",
    )
    deleted_co = _seed_employer_and_company(
        "co_deleted@example.com",
        company_name="Ghost Co",
        company_status="deleted",
    )

    # Origin: Abu Dhabi center (24.4539, 54.3773)
    # 1) ~0 km away (exact center) — tied distance with j_tie
    j_center_1 = _seed_job(
        active_co,
        title="Senior Barista Trainer",
        description="Lead specialty espresso roasting and coffee training.",
        latitude=24.4539,
        longitude=54.3773,
        salary_amount="8000.00",
        schedule="full_time",
        urgency="hot",
    )
    j_center_2 = _seed_job(
        active_co,
        title="Python Backend Engineer",
        description="Build FastAPI microservices and PostgreSQL pipelines.",
        latitude=24.4539,
        longitude=54.3773,
        salary_amount="22000.00",
        schedule="full_time",
        urgency="urgent",
    )
    # 2) ~6.5 km away (inside 10 km radius)
    j_near = _seed_job(
        active_co,
        title="Part-Time Barista",
        description="Morning shifts serving pour-over coffee.",
        latitude=24.5050,
        longitude=54.4100,
        salary_amount="4500.00",
        schedule="part_time",
        urgency="normal",
    )
    # 3) ~125 km away in Dubai (outside 10 km, inside 200 km)
    j_dubai = _seed_job(
        active_co,
        title="Frontend Intern 100%",
        description="React and TypeScript internship working with coffee brands.",
        latitude=25.2048,
        longitude=55.2708,
        location="Dubai, UAE",
        salary_amount=None,
        salary_currency=None,
        schedule="internship",
        urgency="normal",
    )
    # 4) Must NEVER appear in /jobs/open: draft, deleted, or owned by deleted company
    _seed_job(
        active_co,
        title="Draft Barista",
        description="Unpublished draft role.",
        latitude=24.4539,
        longitude=54.3773,
        status="draft",
    )
    _seed_job(
        active_co,
        title="Deleted Barista",
        description="Soft deleted role.",
        latitude=24.4539,
        longitude=54.3773,
        status="deleted",
    )
    _seed_job(
        deleted_co,
        title="Deleted Company Barista",
        description="Open job under deleted company.",
        latitude=24.4539,
        longitude=54.3773,
        status="open",
    )

    with TestClient(build_app(database_url=TEST_DATABASE_URL)) as test_client:
        # 1. Default listing returns only the 4 open jobs of active companies, newest first
        res = test_client.get("/api/jobs/open")
        assert res.status_code == 200
        items = res.json()["items"]
        assert [j["id"] for j in items] == [j_dubai, j_near, j_center_2, j_center_1]
        assert items[0]["company_logo_url"].endswith("/files/logos/1/brand.png")
        assert items[0]["distance_km"] is None

        # 2. Geo radius boundary (10 km keeps 3 Abu Dhabi jobs, excludes Dubai)
        r_geo = test_client.get("/api/jobs/open?lat=24.4539&lng=54.3773&radius_km=10")
        assert r_geo.status_code == 200
        geo_items = r_geo.json()["items"]
        assert {j["id"] for j in geo_items} == {j_center_1, j_center_2, j_near}
        assert all(j["distance_km"] is not None and j["distance_km"] <= 10.0 for j in geo_items)

        # 3. Full-text search on title + description (English stemming via search_vector trigger)
        r_fts = test_client.get("/api/jobs/open?keyword=coffees")
        assert r_fts.status_code == 200
        assert {j["id"] for j in r_fts.json()["items"]} == {j_center_1, j_near, j_dubai}

        r_fts2 = test_client.get("/api/jobs/open?keyword=microservices")
        assert [j["id"] for j in r_fts2.json()["items"]] == [j_center_2]

        # 4. Position substring (case-insensitive, literal '%' escaped)
        r_pos = test_client.get("/api/jobs/open?position=barista")
        assert {j["id"] for j in r_pos.json()["items"]} == {j_center_1, j_near}
        r_pct = test_client.get("/api/jobs/open?position=100%25")
        assert [j["id"] for j in r_pct.json()["items"]] == [j_dubai]

        # 5. Schedule, urgency, salary_min / salary_max filters
        assert [
            j["id"] for j in test_client.get("/api/jobs/open?schedule=part_time").json()["items"]
        ] == [j_near]
        assert [j["id"] for j in test_client.get("/api/jobs/open?urgency=hot").json()["items"]] == [
            j_center_1
        ]
        assert [
            j["id"]
            for j in test_client.get("/api/jobs/open?salary_min=5000&salary_max=15000").json()[
                "items"
            ]
        ] == [j_center_1]
        assert [
            j["id"] for j in test_client.get("/api/jobs/open?salary_min=15000").json()["items"]
        ] == [j_center_2]

        # 6. Combined AND filters: radius + keyword + schedule
        r_combo = test_client.get(
            "/api/jobs/open?lat=24.4539&lng=54.3773&radius_km=10&keyword=coffee&schedule=full_time"
        )
        assert [j["id"] for j in r_combo.json()["items"]] == [j_center_1]

        # 7. Cursor pagination on sort_by=newest (no duplicates, no gaps)
        collected_newest: list[int] = []
        cursor = None
        for _ in range(5):
            url = "/api/jobs/open?limit=2" + (f"&cursor={cursor}" if cursor is not None else "")
            page = test_client.get(url).json()
            collected_newest.extend(j["id"] for j in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert collected_newest == [j_dubai, j_near, j_center_2, j_center_1]

        # 8. sort_by=nearest without coords falls back to newest (200)
        r_nearest_no_coords = test_client.get("/api/jobs/open?sort_by=nearest")
        assert r_nearest_no_coords.status_code == 200
        assert [j["id"] for j in r_nearest_no_coords.json()["items"]] == [
            j_dubai,
            j_near,
            j_center_2,
            j_center_1,
        ]

        # 9. sort_by=nearest with coords & keyset cursor pagination (stable id DESC tie-breaker)
        collected_nearest: list[int] = []
        cursor = None
        for _ in range(5):
            url = "/api/jobs/open?lat=24.4539&lng=54.3773&sort_by=nearest&limit=2" + (
                f"&cursor={cursor}" if cursor is not None else ""
            )
            page = test_client.get(url).json()
            collected_nearest.extend(j["id"] for j in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        # Center tie: j_center_2 (higher id) before j_center_1, then j_near (~6.5 km), then j_dubai
        assert collected_nearest == [j_center_2, j_center_1, j_near, j_dubai]

        # Unknown cursor on nearest sort returns 422 cleanly
        assert (
            test_client.get(
                "/api/jobs/open?lat=24.4539&lng=54.3773&sort_by=nearest&cursor=999999"
            ).status_code
            == 422
        )


@needs_database
def test_explain_uses_gist_and_gin_indexes_for_radius_and_fts():
    """EXPLAIN confirms PostgreSQL uses ix_jobs_location_point (GiST) and ix_jobs_search_vector."""
    alembic("upgrade", "head")
    sql("TRUNCATE users, companies, jobs RESTART IDENTITY CASCADE")
    co_id = _seed_employer_and_company("explain@example.com", company_name="Index Co")
    for idx in range(15):
        _seed_job(
            co_id,
            title=f"Backend Engineer {idx}",
            description="PostgreSQL PostGIS FastAPI distributed systems",
            latitude=24.4539 + idx * 0.001,
            longitude=54.3773 + idx * 0.001,
        )

    async def _explain() -> tuple[str, str]:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with maker() as session:
                await session.execute(text("SET LOCAL enable_seqscan = off"))
                geo_plan = (
                    await session.execute(
                        text(
                            "EXPLAIN (FORMAT JSON) "
                            "SELECT id FROM jobs "
                            "WHERE status = 'open' "
                            "AND ST_DWithin(location_point, "
                            "ST_SetSRID(ST_MakePoint(54.3773, 24.4539), 4326)::geography, 10000)"
                        )
                    )
                ).scalar_one()
                fts_plan = (
                    await session.execute(
                        text(
                            "EXPLAIN (FORMAT JSON) "
                            "SELECT id FROM jobs "
                            "WHERE status = 'open' "
                            "AND search_vector @@ plainto_tsquery('english', 'postgresql')"
                        )
                    )
                ).scalar_one()
                return json.dumps(geo_plan), json.dumps(fts_plan)
        finally:
            await engine.dispose()

    geo_json, fts_json = asyncio.run(_explain())
    assert "ix_jobs_location_point" in geo_json
    assert "ix_jobs_search_vector" in fts_json
