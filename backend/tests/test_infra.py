"""BE-20: real transaction isolation, async routes and test-only database guards."""

from uuid import uuid4

import conftest
import pytest
from conftest import TEST_DATABASE_URL, alembic, build_app, needs_database, transactional_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.mailer import get_mailer


def test_test_database_is_explicit_and_never_uses_application_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:secret@localhost/production")
    monkeypatch.setattr(conftest, "TEST_DATABASE_URL", "")
    assert conftest.database_skip_reason() == "TEST_DATABASE_URL is not set"
    monkeypatch.setattr(
        conftest, "TEST_DATABASE_URL", "postgresql+asyncpg://app:secret@localhost/production"
    )
    assert "database name must contain 'test'" in conftest.database_skip_reason()


def test_route_mailer_records_email_without_network():
    app = build_app()
    mailer = app.dependency_overrides[get_mailer]()
    mailer.send("fixture@example.test", "Verification", "test-only-link")
    assert app.state.test_mailbox.sent == [
        {"to": "fixture@example.test", "subject": "Verification", "body": "test-only-link"}
    ]


@pytest.mark.anyio
async def test_async_client_reaches_health_endpoint(async_client):
    response = await async_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(response.headers["x-request-id"]) == 32


@pytest.mark.anyio
@needs_database
@pytest.mark.parametrize("raise_after_commit", [False, True])
async def test_outer_rollback_preserves_real_commit_and_rollback_semantics(raise_after_commit):
    # A unique ordinary table lets a fresh connection verify teardown, including DDL.
    table = "be20_probe_" + uuid4().hex
    try:
        async with transactional_session() as session:
            await session.execute(text(f"CREATE TABLE {table} (value integer)"))
            await session.commit()
            await session.execute(text(f"INSERT INTO {table} VALUES (1)"))
            await session.commit()
            await session.execute(text(f"INSERT INTO {table} VALUES (2)"))
            await session.rollback()
            rows = (await session.execute(text(f"SELECT value FROM {table}"))).scalars().all()
            assert rows == [1]
            if raise_after_commit:
                raise RuntimeError("simulated test failure")
    except RuntimeError as exc:
        assert raise_after_commit and str(exc) == "simulated test failure"
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            table_name = await connection.scalar(text("SELECT to_regclass(:name)"), {"name": table})
            assert table_name is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
@needs_database
async def test_async_db_client_registers_inside_the_test_transaction(async_db_client, db):
    alembic("upgrade", "head")
    email = f"be20-{uuid4().hex}@example.com"
    response = await async_db_client.post(
        "/api/auth/register", json={"email": email, "password": "fixture password 123"}
    )
    assert response.status_code == 202
    count = await db.scalar(
        text("SELECT count(*) FROM users WHERE email = :email"), {"email": email}
    )
    assert count == 1
    # The service's real commit released a savepoint, not the outer test transaction.
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count(*) FROM users WHERE email = :email"), {"email": email}
            )
            assert count == 0
    finally:
        await engine.dispose()


def test_sync_client_coexists_with_async_infrastructure(client):
    assert client.get("/api/health").json() == {"status": "ok"}
