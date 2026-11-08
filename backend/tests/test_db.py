"""The table base class, checked on the SQL, and which database each app's sessions use."""

import subprocess
import sys
from pathlib import Path
from typing import Annotated

from conftest import build_app
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.db.session import get_session

# A test-only route that answers with the name of the database its session points to.
database_probe = APIRouter()


@database_probe.get("/api/test/database")
async def database_name(session: Annotated[AsyncSession, Depends(get_session)]):
    return {"database": session.bind.url.database}


def test_base_names_constraints_and_mixin_adds_timestamps():
    class Sample(TimestampMixin, Base):
        __tablename__ = "sample"
        id: Mapped[int] = mapped_column(primary_key=True)
        code: Mapped[str] = mapped_column(unique=True)

    try:
        sql = str(CreateTable(Sample.__table__).compile(dialect=postgresql.dialect()))
    finally:
        Base.metadata.remove(Sample.__table__)  # keep the test table out of migrations

    assert "CONSTRAINT pk_sample PRIMARY KEY (id)" in sql
    assert "CONSTRAINT uq_sample_code UNIQUE (code)" in sql
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
    assert "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql


def test_each_app_gets_sessions_on_the_database_from_its_own_settings():
    url = "postgresql+asyncpg://test:test@localhost:5432/"
    # Build both apps first, so neither one can borrow the engine of the other.
    first = build_app(database_url=url + "first_db")
    second = build_app(database_url=url + "second_db")
    for app, name in ((first, "first_db"), (second, "second_db")):
        app.include_router(database_probe)
        with TestClient(app) as client:
            assert client.get("/api/test/database").json() == {"database": name}


def test_shutdown_closes_the_engine_of_that_app(monkeypatch):
    disposed = []

    async def record_dispose(engine, *args, **kwargs):
        disposed.append(engine)

    monkeypatch.setattr(AsyncEngine, "dispose", record_dispose)
    app = build_app()
    with TestClient(app):
        pass  # leaving the block shuts the app down
    assert disposed == [app.state.engine]


def test_the_session_module_loads_every_table():
    """Code that uses the database imports app.db.session, which loads all 17 tables, so a
    foreign key to another domain's table (intro_videos.user_id -> users) can be resolved.
    It runs in a fresh Python, because this test process has already imported every model."""
    code = (
        "import app.db.session; from app.db.base import Base; "
        "print(len(Base.metadata.sorted_tables))"  # sorted_tables follows every foreign key
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "17", result.stderr
