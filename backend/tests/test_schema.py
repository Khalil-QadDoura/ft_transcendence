"""The database schema, checked on a real PostgreSQL with PostGIS.

These tests run `alembic downgrade base`, which deletes every table, so they use their own
database: TEST_DATABASE_URL, whose name must contain "test". Without one they are skipped.
To run them:

    docker run -d --name wozu-test-db -p 5432:5432 -e POSTGRES_PASSWORD=test \
        -e POSTGRES_DB=wozu_test postgis/postgis:15-3.4
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:5432/wozu_test pytest -q
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.companies.models import Company
from app.friends.models import Friendship
from app.jobs.models import Job
from app.users.models import User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
BACKEND_DIR = Path(__file__).resolve().parents[1]

SCHEMA_TABLES = {
    "users",
    "refresh_tokens",
    "password_reset_tokens",
    "friendships",
    "companies",
    "jobs",
}
# Tables that are in the database but are not ours: Alembic's record of the applied
# migrations, and PostGIS's list of map projections.
BOOKKEEPING_TABLES = {"alembic_version", "spatial_ref_sys"}


def skip_reason() -> str | None:
    """Why these tests cannot run here, or None when they can."""
    if not TEST_DATABASE_URL:
        return "TEST_DATABASE_URL is not set"
    url = make_url(TEST_DATABASE_URL)
    if "test" not in (url.database or ""):
        return "the TEST_DATABASE_URL database name must contain 'test'"
    try:
        socket.create_connection((url.host or "localhost", url.port or 5432), timeout=2).close()
    except OSError:
        return f"no database answers at {url.host}:{url.port}"
    return None


pytestmark = [pytest.mark.skipif(bool(skip_reason()), reason=str(skip_reason())), pytest.mark.anyio]


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


def alembic(*args: str) -> str:
    """Run an Alembic command on the test database, as the container does on start."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    """Build the schema once from an empty database for the tests in this file."""
    alembic("downgrade", "base")
    alembic("upgrade", "head")


async def query(sql: str, **params) -> list:
    """Run one SELECT on a fresh connection and return the first column of every row."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        values = list((await connection.execute(text(sql), params)).scalars())
    await engine.dispose()
    return values


async def our_tables() -> set[str]:
    names = await query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    return set(names) - BOOKKEEPING_TABLES


async def columns(table: str) -> set[str]:
    names = await query(
        "SELECT column_name FROM information_schema.columns WHERE table_name = :table",
        table=table,
    )
    return set(names)


@pytest.fixture
async def session():
    """A session for adding rows. It never commits, so its rows vanish after the test."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with AsyncSession(engine) as db_session:
        yield db_session
    await engine.dispose()


async def add(session: AsyncSession, row):
    """Insert one row now (not at commit), so the database checks it right away."""
    session.add(row)
    await session.flush()
    return row


# Building and removing the schema -------------------------------------------------------


async def test_upgrade_on_an_empty_database_creates_our_tables_and_nothing_else():
    alembic("downgrade", "base")
    assert await our_tables() == set()

    alembic("upgrade", "head")
    assert await our_tables() == SCHEMA_TABLES


async def test_models_match_the_migration():
    """`alembic check` compares the models with the database and finds no difference."""
    assert "No new upgrade operations detected" in alembic("check")


async def test_downgrade_removes_every_table_and_type():
    alembic("downgrade", "base")
    try:
        assert await our_tables() == set()
        assert await query("SELECT typname FROM pg_type WHERE typtype = 'e'") == []
    finally:
        alembic("upgrade", "head")


# Accounts ---------------------------------------------------------------------------------


async def test_users_has_no_phone_or_username_columns():
    dropped = {"phone", "is_phone_verified", "deleted_phone", "username"}
    assert dropped.isdisjoint(await columns("users"))


async def test_user_email_is_unique(session):
    await add(session, User(email="ana@example.com"))
    with pytest.raises(IntegrityError, match="uq_users_email"):
        await add(session, User(email="ana@example.com"))


async def test_new_user_gets_the_defaults(session):
    user = await add(session, User(email="ana@example.com"))
    await session.refresh(user)
    assert (user.status, user.is_email_verified, user.token_version) == ("active", False, 1)


async def two_users(session: AsyncSession) -> tuple[int, int]:
    ana = await add(session, User(email="ana@example.com"))
    ben = await add(session, User(email="ben@example.com"))
    return ana.id, ben.id


# Friends ----------------------------------------------------------------------------------


async def test_a_pair_has_one_friendship_whoever_asked(session):
    ana, ben = await two_users(session)
    await add(session, Friendship(requester_id=ana, addressee_id=ben))
    with pytest.raises(IntegrityError, match="uq_friendships_pair"):
        await add(session, Friendship(requester_id=ben, addressee_id=ana))


async def test_a_declined_request_does_not_block_a_new_one(session):
    ana, ben = await two_users(session)
    await add(session, Friendship(requester_id=ana, addressee_id=ben, status="declined"))
    await add(session, Friendship(requester_id=ben, addressee_id=ana))


async def test_nobody_can_befriend_themselves(session):
    ana, _ = await two_users(session)
    with pytest.raises(IntegrityError, match="ck_friendships_not_self"):
        await add(session, Friendship(requester_id=ana, addressee_id=ana))


# Companies and jobs -------------------------------------------------------------------------


async def new_job(session: AsyncSession, **fields) -> Job:
    """A job of a new company; keyword arguments replace the default values."""
    owner = await add(session, User(email="boss@example.com"))
    company = await add(session, Company(owner_user_id=owner.id, name="Sea Cafe"))
    values = {
        "title": "Barista",
        "description": "Make coffee for our guests",
        "latitude": 24.4539,  # Abu Dhabi
        "longitude": 54.3773,
        "location": "Abu Dhabi",
        **fields,
    }
    return await add(session, Job(owner_id=company.id, **values))


async def test_an_owner_has_one_active_company(session):
    owner = await add(session, User(email="boss@example.com"))
    await add(session, Company(owner_user_id=owner.id, name="Old Cafe", status="deleted"))
    await add(session, Company(owner_user_id=owner.id, name="Sea Cafe"))
    with pytest.raises(IntegrityError, match="uq_companies_owner_active"):
        await add(session, Company(owner_user_id=owner.id, name="Second Cafe"))


async def test_job_status_is_draft_open_deleted_and_starts_as_draft(session):
    assert await query("SELECT unnest(enum_range(NULL::job_status))::text") == [
        "draft",
        "open",
        "deleted",
    ]
    job = await new_job(session)
    await session.refresh(job)
    assert job.status == "draft"


@pytest.mark.parametrize(
    ("field", "value", "check"),
    [
        ("latitude", 91, "ck_jobs_latitude_range"),
        ("longitude", -181, "ck_jobs_longitude_range"),
        ("salary_amount", -1, "ck_jobs_salary_not_negative"),
        ("salary_currency", "usd", "ck_jobs_currency_iso_4217"),
    ],
)
async def test_job_checks_reject_bad_values(session, field, value, check):
    with pytest.raises(IntegrityError, match=check):
        await new_job(session, **{field: value})


async def test_job_checks_accept_an_empty_salary(session):
    await new_job(session, salary_amount=None, salary_currency=None)


async def test_trigger_keeps_search_vector_up_to_date(session):
    job = await new_job(session)
    matches = text("SELECT search_vector @@ to_tsquery('english', :word) FROM jobs WHERE id = :id")

    assert await session.scalar(matches, {"word": "coffee", "id": job.id})
    job.description = "Cook breakfast"
    await session.flush()
    assert await session.scalar(matches, {"word": "breakfast", "id": job.id})
    assert not await session.scalar(matches, {"word": "coffee", "id": job.id})


async def test_location_point_follows_latitude_and_longitude(session):
    job = await new_job(session)
    within = text(
        "SELECT ST_DWithin(location_point, ST_MakePoint(55.2708, 25.2048)::geography, :meters) "
        "FROM jobs WHERE id = :id"
    )  # Dubai is about 123 km away
    assert await session.scalar(within, {"meters": 150_000, "id": job.id})
    assert not await session.scalar(within, {"meters": 100_000, "id": job.id})


async def test_jobs_have_a_gist_and_a_gin_index():
    definitions = await query("SELECT indexdef FROM pg_indexes WHERE tablename = 'jobs'")
    assert any("USING gist (location_point)" in d for d in definitions)
    assert any("USING gin (search_vector)" in d for d in definitions)
