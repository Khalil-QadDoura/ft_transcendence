"""The second stage of an account deletion (BE-34): the daily job that anonymises accounts
deleted more than 30 days ago, against a real PostgreSQL and MinIO.

Like tests/test_pictures.py, these tests use only TEST_* variables and skip without them. They
empty the users table (and every table that points at it) and the "anonymise-test" bucket.
The users are made up; Analia's profile is easy to spot, so the log checks can look for it.
"""

import asyncio
import io
import json
import logging
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import date

import pytest
from conftest import (
    BACKEND_DIR,
    DATABASE_SKIP_REASON,
    MINIO_SKIP_REASON,
    TEST_DATABASE_URL,
    alembic,
    build_app,
    sql,
)
from fastapi.testclient import TestClient
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import security
from app.core.config import Settings
from app.core.logging import configure_logging, json_handler
from app.core.storage import Storage
from app.media.moderation import apply_moderation_result
from app.users.anonymise import anonymise_deleted_accounts
from app.worker.celery_app import celery_app
from app.worker.tasks.anonymise import ANONYMISE_TASK

TEST_MINIO_ENDPOINT = os.environ.get("TEST_MINIO_ENDPOINT", "")
TEST_MINIO_ACCESS_KEY = os.environ.get("TEST_MINIO_ACCESS_KEY", "")
TEST_MINIO_SECRET_KEY = os.environ.get("TEST_MINIO_SECRET_KEY", "")
TEST_BUCKET = "anonymise-test"
PASSWORD = "correct horse battery"
PASSWORD_HASH = security.hash_password(PASSWORD)
# Analia's profile, and every piece of it that must never reach a log line.
PROFILE = {
    "first_name": "Analia",
    "last_name": "Zephyrine",
    "position": "Sailing coach",
    "birth_date": date(1994, 5, 17),
    "bio": "Loves the open sea.",
}
PERSONAL = ["analia", "zephyrine", "sailing", "1994-05-17", "open sea"]


def minio_client() -> Minio:
    return Minio(
        TEST_MINIO_ENDPOINT,
        access_key=TEST_MINIO_ACCESS_KEY,
        secret_key=TEST_MINIO_SECRET_KEY,
        secure=False,
    )


# The test database and bucket, for the job and for the app.
ON_TEST_SERVICES = {
    "database_url": TEST_DATABASE_URL,
    "minio_endpoint": TEST_MINIO_ENDPOINT,
    "minio_bucket": TEST_BUCKET,
    "minio_access_key": TEST_MINIO_ACCESS_KEY,
    "minio_secret_key": TEST_MINIO_SECRET_KEY,
}


def settings() -> Settings:
    return Settings(jwt_secret="test-only-jwt-secret-0123456789abcdef", **ON_TEST_SERVICES)


@pytest.fixture(scope="module")
def ready():
    """Skip without a test database and MinIO; otherwise bring the schema up, make the bucket."""
    if not (TEST_MINIO_ACCESS_KEY and TEST_MINIO_SECRET_KEY):
        pytest.skip("TEST_MINIO_ACCESS_KEY or TEST_MINIO_SECRET_KEY is not set")
    if DATABASE_SKIP_REASON or MINIO_SKIP_REASON:
        pytest.skip(DATABASE_SKIP_REASON or MINIO_SKIP_REASON)
    alembic("upgrade", "head")
    if not minio_client().bucket_exists(TEST_BUCKET):
        minio_client().make_bucket(TEST_BUCKET)


@pytest.fixture
def services(ready):
    """Each test starts with no users (CASCADE empties every table that points at them) and
    an empty bucket."""
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    for stored in minio_client().list_objects(TEST_BUCKET, recursive=True):
        minio_client().remove_object(TEST_BUCKET, stored.object_name)


def make_user(email: str, **profile) -> int:
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified, first_name, last_name,"
        " position, birth_date, bio) VALUES (:email, :hash, true, :first_name, :last_name,"
        " :position, :birth_date, :bio) RETURNING id",
        email=email,
        hash=PASSWORD_HASH,
        **{**dict.fromkeys(PROFILE), **profile},
    )
    return user_id


def deleted_days_ago(user_id: int, days: float, hold: bool = False) -> None:
    """The account as DELETE /api/users/me leaves it, that many days ago."""
    sql(
        "UPDATE users SET status = 'deleted', retention_hold = :hold,"
        " deleted_at = now() - :days * interval '1 day' WHERE id = :id",
        id=user_id,
        days=float(days),
        hold=hold,
    )


def store(*keys: str) -> None:
    for key in keys:
        minio_client().put_object(TEST_BUCKET, key, io.BytesIO(b"x"), 1)


def stored() -> set[str]:
    return {item.object_name for item in minio_client().list_objects(TEST_BUCKET, recursive=True)}


def files_of(user_id: int) -> set[str]:
    """A company of this user, and one file in each folder of theirs, as the app names them."""
    [(company_id,)] = sql(
        "INSERT INTO companies (owner_user_id, name) VALUES (:u, 'Cafe') RETURNING id", u=user_id
    )
    keys = {
        f"avatars/{user_id}/a.png",
        f"staging/avatars/{user_id}/b.png",
        f"users/{user_id}/intro/c.mp4",
        f"videos/{user_id}/d.mp4",
        f"logos/{company_id}/e.png",
        f"staging/logos/{company_id}/f.png",
    }
    store(*keys)
    return keys


def set_avatar(user_id: int) -> None:
    """The avatar this account had: in the row and in storage."""
    key = f"avatars/{user_id}/a.png"
    sql("UPDATE users SET avatar_object_key = :key WHERE id = :id", key=key, id=user_id)
    store(key)


def add_video(user_id: int, lifecycle: str = "posted") -> int:
    [(video_id,)] = sql(
        "INSERT INTO intro_videos (user_id, object_key, duration_sec, size_bytes, content_type,"
        " lifecycle_status) VALUES (:u, :key, 20, 1, 'video/mp4', :lifecycle) RETURNING id",
        u=user_id,
        key=f"videos/{user_id}/v{lifecycle}.mp4",
        lifecycle=lifecycle,
    )
    return video_id


def account(user_id: int) -> dict:
    [row] = sql(
        "SELECT email, password_hash, first_name, last_name, position, birth_date, bio,"
        " avatar_object_key, status, anonymised_at IS NOT NULL AS anonymised, updated_at"
        " FROM users WHERE id = :id",
        id=user_id,
    )
    return dict(row._mapping)


def is_anonymised(user_id: int) -> bool:
    row = account(user_id)
    personal = [row[field] for field in (*PROFILE, "password_hash", "avatar_object_key")]
    return row["email"] == f"deleted-{user_id}@invalid" and row["anonymised"] and not any(personal)


async def one_run(storage: Storage, older_than_days: int = 30):
    """One run of the job on its own database connection, as the worker makes it."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await anonymise_deleted_accounts(session, storage, older_than_days)
    finally:
        await engine.dispose()


def run_job(older_than_days: int = 30, storage: Storage | None = None):
    return asyncio.run(one_run(storage or Storage(settings()), older_than_days))


@contextmanager
def captured_logs():
    """The JSON log lines written inside the `with` block, as dicts."""
    configure_logging("INFO")
    stream = io.StringIO()
    handler = json_handler(stream)
    logging.getLogger().addHandler(handler)
    lines: list[dict] = []
    try:
        yield lines
    finally:
        logging.getLogger().removeHandler(handler)
        lines.extend(json.loads(line) for line in stream.getvalue().splitlines())


def pause_on_first_delete(storage: Storage) -> tuple[threading.Event, threading.Event]:
    """The job stops at its first file delete, holding the account's locks, until `go`."""
    started, go = threading.Event(), threading.Event()
    real_remove = storage.remove

    def remove(key: str) -> None:
        started.set()
        assert go.wait(10)
        real_remove(key)

    storage.remove = remove
    return started, go


# --- The daily job -------------------------------------------------------------------------


def test_the_worker_runs_the_job_every_day_at_midnight_utc():
    entry = celery_app.conf.beat_schedule["anonymise-deleted-accounts"]
    assert entry["task"] == ANONYMISE_TASK and ANONYMISE_TASK in celery_app.tasks
    assert entry["schedule"].hour == {0} and entry["schedule"].minute == {0}


def test_deleted_31_days_ago_is_anonymised_29_days_ago_is_not(services):
    old = make_user("analia@example.com", **PROFILE)
    recent = make_user("ben@example.com", **PROFILE)
    active = make_user("cara@example.com", **PROFILE)
    deleted_days_ago(old, 31)
    deleted_days_ago(recent, 29)
    files = {user_id: files_of(user_id) for user_id in (old, recent, active)}
    set_avatar(old)
    # Files of user 10 and of company 10: the folders of user 1 and company 1 must not reach them.
    others = {f"avatars/{old}0/x.png", f"logos/{old}0/x.png"}
    store(*others)
    before = {user_id: account(user_id) for user_id in (recent, active)}

    result = run_job()

    assert result.anonymised == [old] and result.failed == []
    assert is_anonymised(old) and account(old)["status"] == "deleted"
    assert {user_id: account(user_id) for user_id in (recent, active)} == before
    assert stored() == files[recent] | files[active] | others


def test_an_account_on_hold_is_kept_until_the_hold_is_lifted(services):
    held = make_user("analia@example.com", **PROFILE)
    deleted_days_ago(held, 90, hold=True)
    files = files_of(held)
    before = account(held)

    assert run_job(older_than_days=0).anonymised == []
    assert account(held) == before and stored() == files

    sql("UPDATE users SET retention_hold = false WHERE id = :id", id=held)
    assert run_job().anonymised == [held]
    assert is_anonymised(held) and stored() == set()


def test_a_second_run_changes_nothing(services):
    user_id = make_user("analia@example.com", **PROFILE)
    deleted_days_ago(user_id, 31)
    assert run_job().anonymised == [user_id]
    after_first = account(user_id)
    store(f"avatars/{user_id}/late.png")  # even a file that appears later is left alone

    second = run_job()

    assert second.anonymised == [] and second.failed == []
    assert account(user_id) == after_first
    assert stored() == {f"avatars/{user_id}/late.png"}


def test_videos_are_marked_deleted_and_the_records_stay_linked(services):
    analia = make_user("analia@example.com", **PROFILE)
    ben = make_user("ben@example.com")
    [(company_id,)] = sql(
        "INSERT INTO companies (owner_user_id, name) VALUES (:u, 'Cafe') RETURNING id", u=ben
    )
    [(job_id,)] = sql(
        "INSERT INTO jobs (owner_id, title, description, latitude, longitude, location, status)"
        " VALUES (:c, 'Barista', 'Coffee', 24.4, 54.3, 'Abu Dhabi', 'open') RETURNING id",
        c=company_id,
    )
    sql(
        "INSERT INTO applications (job_id, applicant_id, company_id) VALUES (:j, :u, :c)",
        j=job_id,
        u=analia,
        c=company_id,
    )
    [(room_id,)] = sql("INSERT INTO game_rooms (target_size) VALUES (3) RETURNING id")
    sql(
        "INSERT INTO game_participants (room_id, user_id, display_label, score)"
        " VALUES (:r, :u, 'Player 1', 7)",
        r=room_id,
        u=analia,
    )
    videos = [add_video(analia, "posted"), add_video(analia, "loaded")]
    deleted_days_ago(analia, 31)

    assert run_job().anonymised == [analia]

    assert sql("SELECT lifecycle_status FROM intro_videos ORDER BY id") == [("deleted",)] * 2
    assert sql("SELECT id FROM intro_videos ORDER BY id") == [(v,) for v in videos]
    assert sql("SELECT applicant_id, status FROM applications") == [(analia, "submitted")]
    assert sql("SELECT user_id, display_label, score FROM game_participants") == [
        (analia, "Player 1", 7)
    ]


def test_a_failed_file_delete_saves_nothing_and_the_next_run_finishes(services):
    user_id = make_user("analia@example.com", **PROFILE)
    deleted_days_ago(user_id, 31)
    files_of(user_id)
    before = account(user_id)
    storage = Storage(settings())
    calls = []
    real_remove = storage.remove

    def second_delete_fails(key: str) -> None:
        calls.append(key)
        if len(calls) == 2:
            raise ConnectionError(f"MinIO is down while deleting {key}")
        real_remove(key)

    storage.remove = second_delete_fails
    with captured_logs() as logs:
        result = run_job(storage=storage)

    assert result.anonymised == [] and result.failed == [user_id]
    assert account(user_id) == before  # nothing saved: the account is still due
    assert len(stored()) == 5  # the first file went, the rest stayed
    failed = [line for line in logs if line["event"].startswith("account not anonymised")]
    assert [(line["user_id"], line["error"]) for line in failed] == [(user_id, "ConnectionError")]

    assert run_job().anonymised == [user_id]
    assert is_anonymised(user_id) and stored() == set()


def test_the_log_lines_name_only_the_account_id(services):
    user_id = make_user("analia.zephyrine@example.com", **PROFILE)
    deleted_days_ago(user_id, 31)
    with captured_logs() as logs:
        run_job()
    [line] = [line for line in logs if line["event"] == "account anonymised"]
    assert set(line) == {"event", "user_id", "logger", "level", "timestamp"}
    assert line["user_id"] == user_id
    text = json.dumps(logs).lower()
    assert not [word for word in PERSONAL if word in text]


# --- Two things at once --------------------------------------------------------------------


def test_two_runs_at_once_anonymise_an_account_once(services):
    user_id = make_user("analia@example.com", **PROFILE)
    deleted_days_ago(user_id, 31)
    files_of(user_id)

    async def scenario():
        paused = Storage(settings())
        started, go = pause_on_first_delete(paused)
        first = asyncio.create_task(one_run(paused))
        assert await asyncio.to_thread(started.wait, 10)  # it holds the account's lock now
        second = asyncio.create_task(one_run(Storage(settings())))
        await asyncio.sleep(0.5)
        assert not second.done()  # the second waits for that lock...
        go.set()
        return await first, await second

    first, second = asyncio.run(scenario())
    # ...then reads the row again and finds it anonymised: nothing more to do.
    assert first.anonymised == [user_id] and second.anonymised == [] and second.failed == []
    assert is_anonymised(user_id) and stored() == set()


def test_a_hold_set_while_the_job_waits_keeps_the_account(services):
    user_id = make_user("analia@example.com", **PROFILE)
    deleted_days_ago(user_id, 31)
    before = account(user_id)

    async def scenario():
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.connect() as team:
            # A team member opens a dispute: the row is locked until the hold is saved.
            await team.exec_driver_sql(f"SELECT 1 FROM users WHERE id = {user_id} FOR UPDATE")
            job = asyncio.create_task(one_run(Storage(settings())))
            await asyncio.sleep(0.5)
            assert not job.done()  # the job listed the account but waits for its lock
            await team.exec_driver_sql(
                f"UPDATE users SET retention_hold = true WHERE id = {user_id}"
            )
            await team.commit()
        await engine.dispose()
        return await job

    result = asyncio.run(scenario())
    assert result.anonymised == [] and result.failed == []
    assert account(user_id) == before


def test_a_moderation_result_that_meets_the_job_finds_the_video_deleted(services):
    user_id = make_user("analia@example.com", **PROFILE)
    deleted_days_ago(user_id, 31)
    set_avatar(user_id)
    video_id = add_video(user_id, "loaded")

    async def scenario():
        paused = Storage(settings())
        started, go = pause_on_first_delete(paused)
        job = asyncio.create_task(one_run(paused))
        assert await asyncio.to_thread(started.wait, 10)
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            moderation = asyncio.create_task(
                apply_moderation_result(
                    session, None, video_id=video_id, moderation_status="approved"
                )
            )
            await asyncio.sleep(0.5)
            assert not moderation.done()  # it waits for the account's lock
            go.set()
            saved = await moderation
        await engine.dispose()
        return await job, saved

    result, saved = asyncio.run(scenario())
    assert result.anonymised == [user_id] and saved is None
    assert sql("SELECT moderation_status, lifecycle_status FROM intro_videos") == [
        ("pending", "deleted")
    ]


# --- On demand, for the demo ---------------------------------------------------------------


def test_the_command_with_0_days_anonymises_a_fresh_deletion_but_not_a_hold(services):
    fresh = make_user("analia@example.com", **PROFILE)
    held = make_user("ben@example.com", **PROFILE)
    deleted_days_ago(fresh, 1 / 24)  # an hour ago
    deleted_days_ago(held, 1 / 24, hold=True)
    files_of(fresh)
    env = {
        **os.environ,
        "DATABASE_URL": TEST_DATABASE_URL,
        "MINIO_ENDPOINT": TEST_MINIO_ENDPOINT,
        "MINIO_BUCKET": TEST_BUCKET,
        "MINIO_ACCESS_KEY": TEST_MINIO_ACCESS_KEY,
        "MINIO_SECRET_KEY": TEST_MINIO_SECRET_KEY,
    }

    def command(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "app.worker.tasks.anonymise", *args],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    # Without the flag, the 30 days apply: an hour-old deletion is not due.
    assert command().returncode == 0
    assert not is_anonymised(fresh) and len(stored()) == 6

    done = command("--older-than-days", "0")

    assert done.returncode == 0, done.stderr
    assert is_anonymised(fresh) and stored() == set()
    assert not is_anonymised(held)
    lines = [json.loads(line) for line in done.stdout.splitlines()]
    assert [line["user_id"] for line in lines if line["event"] == "account anonymised"] == [fresh]
    assert not [word for word in PERSONAL if word in done.stdout.lower()]


# --- "Deleted user" in the API --------------------------------------------------------------


def test_a_deleted_account_shows_as_deleted_user_in_chat_and_applications(services):
    analia = make_user("analia@example.com", **PROFILE)
    ben = make_user("ben@example.com", first_name="Ben")
    [(company_id,)] = sql(
        "INSERT INTO companies (owner_user_id, name) VALUES (:u, 'Cafe') RETURNING id", u=ben
    )
    [(job_id,)] = sql(
        "INSERT INTO jobs (owner_id, title, description, latitude, longitude, location, status)"
        " VALUES (:c, 'Barista', 'Coffee', 24.4, 54.3, 'Abu Dhabi', 'open') RETURNING id",
        c=company_id,
    )
    video_id = add_video(analia, "posted")
    sql(
        "INSERT INTO applications (job_id, applicant_id, company_id, intro_video_id)"
        " VALUES (:j, :u, :c, :v)",
        j=job_id,
        u=analia,
        c=company_id,
        v=video_id,
    )
    [(conv_id,)] = sql("INSERT INTO conversations (type) VALUES ('direct') RETURNING id")
    for user_id in (analia, ben):
        sql(
            "INSERT INTO conversation_participants (conversation_id, user_id) VALUES (:c, :u)",
            c=conv_id,
            u=user_id,
        )
    sql(
        "INSERT INTO messages (conversation_id, author_id, content) VALUES (:c, :u, 'Hello Ben')",
        c=conv_id,
        u=analia,
    )
    deleted_user = {
        "id": analia,
        "first_name": None,
        "last_name": None,
        "display_name": "Deleted user",
        "avatar_url": "/api/media/avatar/default.svg",
    }

    with TestClient(build_app(**ON_TEST_SERVICES)) as client:

        def login(email: str) -> dict:
            body = {"email": email, "password": PASSWORD}
            token = client.post("/api/auth/login", json=body).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}

        def what_ben_sees() -> tuple[dict, dict]:
            """The chat peer (in the list and alone) and the application, as Ben gets them.
            Analia's message stays, whatever happens to her account."""
            [conversation] = client.get("/api/conversations", headers=as_ben).json()
            single = client.get(f"/api/conversations/{conv_id}", headers=as_ben).json()
            assert single["peer"] == conversation["peer"]
            messages = client.get(f"/api/conversations/{conv_id}/messages", headers=as_ben)
            [message] = messages.json()["items"]
            assert (message["author_id"], message["content"]) == (analia, "Hello Ben")
            [application] = client.get(f"/api/jobs/{job_id}/applications", headers=as_ben).json()[
                "items"
            ]
            return conversation["peer"], application

        def ben_sees_a_deleted_user() -> None:
            peer, application = what_ben_sees()
            assert peer == deleted_user
            assert application["applicant_id"] == analia
            assert application["applicant_display_name"] == "Deleted user"
            for field in ("first_name", "last_name", "position"):
                assert application[f"applicant_{field}"] is None
            assert application["applicant_avatar_url"] == "/api/media/avatar/default.svg"
            assert application["intro_video_url"] is None
            profile = client.get(f"/api/users/{analia}/profile", headers=as_ben)
            assert profile.status_code == 404

        as_ben = login("ben@example.com")
        peer, application = what_ben_sees()
        assert peer["display_name"] == "Analia Zephyrine"
        assert application["applicant_display_name"] == "Analia Zephyrine"
        assert application["intro_video_url"]

        # Stage 1: Analia deletes her account, which records when.
        response = client.delete("/api/users/me", headers=login("analia@example.com"))
        assert response.status_code == 204
        [(recorded,)] = sql(
            "SELECT deleted_at > now() - interval '1 minute' FROM users WHERE id = :id", id=analia
        )
        assert recorded
        ben_sees_a_deleted_user()

        # Stage 2: 30 days later, the job anonymises her. Ben sees the same.
        deleted_days_ago(analia, 31)
        assert run_job().anonymised == [analia]
        ben_sees_a_deleted_user()

        # Her email is free again: signing up with it makes a new account.
        body = {"email": "analia@example.com", "password": PASSWORD}
        assert client.post("/api/auth/register", json=body).status_code == 202
        assert sql("SELECT count(*) FROM users WHERE email = 'analia@example.com'") == [(1,)]
