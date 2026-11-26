"""Integration tests for BE-32 demo seed script & reset (`make seed`, `make reset-demo`)."""

from __future__ import annotations

import asyncio
import io
import os
from collections.abc import Iterator

import pytest
import redis
from conftest import (
    DATABASE_SKIP_REASON,
    MINIO_SKIP_REASON,
    REDIS_SKIP_REASON,
    TEST_DATABASE_URL,
    TEST_REDIS_URL,
    alembic,
    build_app,
    sql,
)
from fastapi.testclient import TestClient
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.storage import Storage
from app.seed import SeedSummary, main, reset_demo, seed_demo
from app.seed.data import DEMO_PASSWORD

TEST_MINIO_ENDPOINT = os.environ.get("TEST_MINIO_ENDPOINT", "")
TEST_MINIO_ACCESS_KEY = os.environ.get("TEST_MINIO_ACCESS_KEY", "")
TEST_MINIO_SECRET_KEY = os.environ.get("TEST_MINIO_SECRET_KEY", "")
TEST_BUCKET = "seed-test"


def _minio_client() -> Minio:
    return Minio(
        TEST_MINIO_ENDPOINT,
        access_key=TEST_MINIO_ACCESS_KEY,
        secret_key=TEST_MINIO_SECRET_KEY,
        secure=False,
    )


def _settings(**overrides: object) -> Settings:
    data = {
        "jwt_secret": "test-only-jwt-secret-0123456789abcdef",
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "minio_endpoint": TEST_MINIO_ENDPOINT,
        "minio_external_endpoint": f"http://{TEST_MINIO_ENDPOINT}",
        "minio_bucket": TEST_BUCKET,
        "minio_access_key": TEST_MINIO_ACCESS_KEY,
        "minio_secret_key": TEST_MINIO_SECRET_KEY,
        "game_scheduler_enabled": False,
    }
    data.update(overrides)
    return Settings(**data)


@pytest.fixture(scope="module")
def ready() -> None:
    if not (TEST_MINIO_ACCESS_KEY and TEST_MINIO_SECRET_KEY):
        pytest.skip("TEST_MINIO_ACCESS_KEY or TEST_MINIO_SECRET_KEY is not set")
    if DATABASE_SKIP_REASON or MINIO_SKIP_REASON or REDIS_SKIP_REASON:
        pytest.skip(DATABASE_SKIP_REASON or MINIO_SKIP_REASON or REDIS_SKIP_REASON)
    alembic("upgrade", "head")
    client = _minio_client()
    if not client.bucket_exists(TEST_BUCKET):
        client.make_bucket(TEST_BUCKET)


@pytest.fixture
def clean_env(ready) -> Iterator[redis.Redis]:
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    client = _minio_client()
    for stored in client.list_objects(TEST_BUCKET, recursive=True):
        client.remove_object(TEST_BUCKET, stored.object_name)

    rclient = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    for pattern in ("ws:*", "game:*", "presence:*", "rate:*", "job_view:*", "worker:*"):
        for key in rclient.scan_iter(pattern):
            rclient.delete(key)
    yield rclient
    rclient.close()


async def _run_seed(**kwargs) -> SeedSummary:
    cfg = kwargs.pop("settings", _settings())
    engine = create_async_engine(cfg.database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await seed_demo(session, Storage(cfg), settings=cfg, **kwargs)
    finally:
        await engine.dispose()


async def _run_reset(rclient: redis.Redis, **kwargs) -> SeedSummary:
    cfg = kwargs.pop("settings", _settings())
    engine = create_async_engine(cfg.database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await reset_demo(
                session, Storage(cfg), redis_client=rclient, settings=cfg, **kwargs
            )
    finally:
        await engine.dispose()


def test_create_app_never_seeds_automatically(clean_env) -> None:
    app = build_app(
        database_url=TEST_DATABASE_URL,
        redis_url=TEST_REDIS_URL,
        minio_endpoint=TEST_MINIO_ENDPOINT,
        minio_bucket=TEST_BUCKET,
        minio_access_key=TEST_MINIO_ACCESS_KEY,
        minio_secret_key=TEST_MINIO_SECRET_KEY,
    )
    with TestClient(app):
        assert sql("SELECT COUNT(*) FROM users") == [(0,)]


def test_seed_demo_populates_all_domains_and_media(clean_env) -> None:
    summary = asyncio.run(_run_seed())
    assert summary.users_created == 6
    assert summary.companies_created == 2
    assert summary.jobs_created == 22
    assert summary.videos_created == 5
    assert summary.applications_created == 7
    assert summary.friendships_created == 3
    assert summary.conversations_created == 3
    assert summary.messages_created == 7
    assert summary.moderation_queued == 0

    # 20 open jobs: 10 in Abu Dhabi, 10 in Baku; plus 2 drafts.
    assert sql("SELECT COUNT(*) FROM jobs WHERE status = 'open'") == [(20,)]
    assert sql("SELECT COUNT(*) FROM jobs WHERE status = 'draft'") == [(2,)]
    abu_dhabi_count = sql(
        "SELECT COUNT(*) FROM jobs WHERE status = 'open' AND latitude BETWEEN 24 AND 25"
    )
    baku_count = sql(
        "SELECT COUNT(*) FROM jobs WHERE status = 'open' AND latitude BETWEEN 40 AND 41"
    )
    assert abu_dhabi_count == [(10,)]
    assert baku_count == [(10,)]

    # Applications span every active status with matching audit events.
    statuses = {row[0] for row in sql("SELECT DISTINCT status::text FROM applications")}
    assert statuses == {"submitted", "viewed", "shortlisted", "contacted", "hired", "rejected"}
    assert sql("SELECT COUNT(*) FROM application_events")[0][0] >= 15

    # Every avatar, company logo and intro video is stored in MinIO.
    storage = Storage(_settings())
    for (avatar_key,) in sql("SELECT avatar_object_key FROM users"):
        assert avatar_key is not None and storage.stat(avatar_key) is not None
    for (logo_key,) in sql("SELECT logo_object_key FROM companies"):
        assert logo_key is not None and storage.stat(logo_key) is not None
    for (video_key,) in sql("SELECT object_key FROM intro_videos"):
        assert storage.stat(video_key) is not None
        header = storage.first_bytes(video_key, 8)
        assert header[4:8] == b"ftyp"


def test_seed_demo_is_idempotent_and_repairs_missing_media(clean_env) -> None:
    first = asyncio.run(_run_seed())
    assert first.users_created == 6

    # Delete one video from MinIO; re-running seed must restore the object without duplicating rows.
    [(video_key,)] = sql("SELECT object_key FROM intro_videos LIMIT 1")
    Storage(_settings()).remove(video_key)
    assert Storage(_settings()).stat(video_key) is None

    second = asyncio.run(_run_seed())
    assert second == SeedSummary()
    assert sql("SELECT COUNT(*) FROM users") == [(6,)]
    assert sql("SELECT COUNT(*) FROM jobs") == [(22,)]
    assert sql("SELECT COUNT(*) FROM applications") == [(7,)]
    assert sql("SELECT COUNT(*) FROM messages") == [(7,)]
    assert Storage(_settings()).stat(video_key) is not None


def test_seeded_accounts_and_data_work_through_real_api(clean_env) -> None:
    asyncio.run(_run_seed())
    app = build_app(
        database_url=TEST_DATABASE_URL,
        redis_url=TEST_REDIS_URL,
        minio_endpoint=TEST_MINIO_ENDPOINT,
        minio_external_endpoint=f"http://{TEST_MINIO_ENDPOINT}",
        minio_bucket=TEST_BUCKET,
        minio_access_key=TEST_MINIO_ACCESS_KEY,
        minio_secret_key=TEST_MINIO_SECRET_KEY,
    )
    with TestClient(app) as client:
        # 1. Employer signs in and sees posted candidate pitch videos & Abu Dhabi jobs.
        emp_login = client.post(
            "/api/auth/login",
            json={"email": "employer1@wozu.demo", "password": DEMO_PASSWORD},
            headers={"X-Real-IP": "10.50.0.1"},
        )
        assert emp_login.status_code == 200
        emp_hdr = {"Authorization": f"Bearer {emp_login.json()['access_token']}"}

        feed = client.get("/api/media/feed", headers=emp_hdr)
        assert feed.status_code == 200
        assert len(feed.json()["items"]) == 4

        abu_dhabi = client.get("/api/jobs/open?lat=24.47&lng=54.37&radius_km=50")
        assert abu_dhabi.status_code == 200
        assert len(abu_dhabi.json()["items"]) == 10

        baku = client.get("/api/jobs/open?lat=40.38&lng=49.86&radius_km=50")
        assert baku.status_code == 200
        assert len(baku.json()["items"]) == 10

        mine = client.get("/api/jobs/mine", headers=emp_hdr)
        assert mine.status_code == 200
        assert len(mine.json()) == 11

        # 2. Candidate signs in and sees unread direct conversations + friendships.
        cand_login = client.post(
            "/api/auth/login",
            json={"email": "candidate1@wozu.demo", "password": DEMO_PASSWORD},
            headers={"X-Real-IP": "10.50.0.2"},
        )
        assert cand_login.status_code == 200
        cand_hdr = {"Authorization": f"Bearer {cand_login.json()['access_token']}"}

        convs = client.get("/api/conversations", headers=cand_hdr)
        assert convs.status_code == 200
        assert any(c["unread_count"] > 0 for c in convs.json())

        friends = client.get("/api/friends", headers=cand_hdr)
        assert friends.status_code == 200
        assert len(friends.json()) == 2


def test_reset_demo_wipes_extra_data_and_reseeds(clean_env) -> None:
    asyncio.run(_run_seed())

    # Simulate user-created records/files/cache before reset-demo.
    sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES ('extra@example.com', 'hash', true)"
    )
    _minio_client().put_object(TEST_BUCKET, "avatars/999/old.png", io.BytesIO(b"old"), 3)
    clean_env.set("ws:ticket:stale", "1")
    clean_env.set("worker:heartbeat", "1")

    summary = asyncio.run(_run_reset(clean_env))
    assert summary.users_created == 6
    assert sql("SELECT COUNT(*) FROM users WHERE email = 'extra@example.com'") == [(0,)]
    assert Storage(_settings()).stat("avatars/999/old.png") is None
    assert clean_env.get("ws:ticket:stale") is None
    assert clean_env.get("worker:heartbeat") == "1"


def test_seed_optional_live_moderation_flag(clean_env) -> None:
    queued: list[tuple[int, str]] = []
    cfg = _settings(openai_api_key="test-openai-placeholder-for-mocked-queue")
    summary = asyncio.run(
        _run_seed(
            moderate=True,
            enqueue_fn=lambda vid, key: queued.append((vid, key)),
            settings=cfg,
        )
    )
    assert summary.moderation_queued == 1
    assert len(queued) == 1
    assert sql("SELECT COUNT(*) FROM intro_videos WHERE moderation_status = 'pending'") == [(1,)]


def test_seed_cli_main_and_reset_flag(clean_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-only-jwt-secret-0123456789abcdef")
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setenv("MINIO_ENDPOINT", TEST_MINIO_ENDPOINT)
    monkeypatch.setenv("MINIO_EXTERNAL_ENDPOINT", f"http://{TEST_MINIO_ENDPOINT}")
    monkeypatch.setenv("MINIO_BUCKET", TEST_BUCKET)
    monkeypatch.setenv("MINIO_ACCESS_KEY", TEST_MINIO_ACCESS_KEY)
    monkeypatch.setenv("MINIO_SECRET_KEY", TEST_MINIO_SECRET_KEY)
    get_settings.cache_clear()
    try:
        assert main([]) == 0
        assert sql("SELECT COUNT(*) FROM jobs WHERE status = 'open'") == [(20,)]
        assert main(["--reset"]) == 0
        assert sql("SELECT COUNT(*) FROM users") == [(6,)]
    finally:
        get_settings.cache_clear()
