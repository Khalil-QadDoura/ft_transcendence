"""Intro videos (/api/media) against real services: PostgreSQL, MinIO and Redis.

The files really go up to MinIO with an HTTP PUT, as the browser does, and confirm checks them
there; the moderation task really lands on a Redis queue. The users and the files are made up:
the "videos" are a few bytes that start like an MP4 file.

These tests use only TEST_* variables, and skip without them. They empty the users table (and
every table that points at it), the "media-test" bucket and the queue, so use throwaway
containers:
    docker run -d --name wozu-test-minio -p 9000:9000 -e MINIO_ROOT_USER=test \\
        -e MINIO_ROOT_PASSWORD=test-secret pgsty/minio:RELEASE.2026-08-04T00-00-00Z server /data
    docker run -d --name wozu-test-redis -p 6379:6379 redis:7-alpine
    TEST_MINIO_ENDPOINT=localhost:9000 TEST_MINIO_ACCESS_KEY=test \\
        TEST_MINIO_SECRET_KEY=test-secret TEST_REDIS_URL=redis://localhost:6379/0 \\
        TEST_DATABASE_URL=... pytest tests/test_media.py
"""

import io
import json
import logging
import os
import re
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx2
import pytest
from conftest import DATABASE_SKIP_REASON, TEST_DATABASE_URL, alembic, build_app, sql
from fastapi.testclient import TestClient
from kombu import Connection
from minio import Minio

from app.auth import security
from app.core.config import Settings
from app.core.logging import json_handler
from app.core.queue import MODERATION_TASK
from app.core.storage import Storage
from app.media.constants import MAX_SIZE_BYTES

TEST_MINIO_ENDPOINT = os.environ.get("TEST_MINIO_ENDPOINT", "")  # host:port, plain HTTP
TEST_MINIO_ACCESS_KEY = os.environ.get("TEST_MINIO_ACCESS_KEY", "")
TEST_MINIO_SECRET_KEY = os.environ.get("TEST_MINIO_SECRET_KEY", "")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "")
TEST_BUCKET = "media-test"
# In the tests the browser reaches MinIO directly, so the links are signed for it.
EXTERNAL = f"http://{TEST_MINIO_ENDPOINT}"
# Celery's default queue: the one the API writes to and the worker reads.
QUEUE = "celery"

PASSWORD = "correct horse battery"
# Argon2 is slow on purpose, so the hash is made once and shared by every test user.
PASSWORD_HASH = security.hash_password(PASSWORD)

# The first 24 bytes of a real MP4 file: its "ftyp" (file type) box, brand "isom".
MP4_START = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
# What a key made by upload-url looks like, for user 1.
KEY_OF_USER_1 = re.compile(r"users/1/intro/[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}\.mp4")


def made_up_mp4(size: int = 2048) -> bytes:
    """A small made-up file that starts like an MP4; the rest is zeros."""
    return MP4_START + bytes(size - len(MP4_START))


def services_skip_reason() -> str | None:
    """Why these tests cannot run here, or None when they can."""
    if DATABASE_SKIP_REASON:
        return DATABASE_SKIP_REASON
    if not (TEST_MINIO_ENDPOINT and TEST_MINIO_ACCESS_KEY and TEST_MINIO_SECRET_KEY):
        return "TEST_MINIO_ENDPOINT, TEST_MINIO_ACCESS_KEY or TEST_MINIO_SECRET_KEY is not set"
    if not TEST_REDIS_URL:
        return "TEST_REDIS_URL is not set"
    redis = urlparse(TEST_REDIS_URL)
    for host, port in [TEST_MINIO_ENDPOINT.rsplit(":", 1), (redis.hostname, redis.port or 6379)]:
        try:
            socket.create_connection((host, int(port)), timeout=2).close()
        except OSError:
            return f"nothing answers at {host}:{port}"
    return None


def minio_client() -> Minio:
    """Our own MinIO client, to look into the test bucket."""
    return Minio(
        TEST_MINIO_ENDPOINT,
        access_key=TEST_MINIO_ACCESS_KEY,
        secret_key=TEST_MINIO_SECRET_KEY,
        secure=False,
    )


def media_app(**overrides: object):
    """An app on the test database, the test bucket and the test queue."""
    settings = {
        "database_url": TEST_DATABASE_URL,
        "minio_endpoint": TEST_MINIO_ENDPOINT,
        "minio_external_endpoint": EXTERNAL,
        "minio_bucket": TEST_BUCKET,
        "minio_access_key": TEST_MINIO_ACCESS_KEY,
        "minio_secret_key": TEST_MINIO_SECRET_KEY,
        "redis_url": TEST_REDIS_URL,
        **overrides,
    }
    return build_app(**settings)


def take_queued_tasks() -> list[tuple[str, list]]:
    """Take every task off the test queue, the way the worker does: (task name, arguments)."""
    tasks = []
    with Connection(TEST_REDIS_URL) as connection:
        queue = connection.SimpleQueue(QUEUE)
        while True:
            try:
                message = queue.get_nowait()
            except queue.Empty:
                break
            arguments, _keyword_arguments, _options = message.payload
            tasks.append((message.headers["task"], arguments))
            message.ack()
        queue.close()
    return tasks


@pytest.fixture(scope="module")
def services():
    """Skip without the three services; otherwise bring the schema up and make the bucket."""
    reason = services_skip_reason()
    if reason:
        pytest.skip(reason)
    alembic("upgrade", "head")
    if not minio_client().bucket_exists(TEST_BUCKET):
        minio_client().make_bucket(TEST_BUCKET)


@pytest.fixture
def client(services):
    """This file's client. Each test starts with no users, an empty bucket and no tasks."""
    # CASCADE also empties intro_videos, companies, jobs and applications.
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    minio = minio_client()
    for stored in minio.list_objects(TEST_BUCKET, recursive=True):
        minio.remove_object(TEST_BUCKET, stored.object_name)
    take_queued_tasks()
    with TestClient(media_app()) as test_client:
        yield test_client


class Account(NamedTuple):
    id: int
    headers: dict  # {"Authorization": "Bearer <access token>"}


def add_user(email: str, position: str | None = None, **profile) -> int:
    """A verified account added straight to the database; returns its id."""
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified, position, first_name,"
        " last_name) VALUES (:email, :hash, true, :position, :first_name, :last_name)"
        " RETURNING id",
        email=email,
        hash=PASSWORD_HASH,
        position=position,
        first_name=profile.get("first_name"),
        last_name=profile.get("last_name"),
    )
    return user_id


def make_user(client, email: str, position: str | None = None, **profile) -> Account:
    """A new account, logged in through the real /api/auth/login."""
    user_id = add_user(email, position, **profile)
    tokens = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()
    return Account(user_id, {"Authorization": f"Bearer {tokens['access_token']}"})


@pytest.fixture
def ana(client) -> Account:
    return make_user(client, "ana@example.com", "Barista", first_name="Ana", last_name="Silva")


@pytest.fixture
def ben(client) -> Account:
    return make_user(client, "ben@example.com", "Driver")


def ask_upload_url(client, account: Account, **body):
    return client.post("/api/media/intro-video/upload-url", json=body, headers=account.headers)


def put_file(url: str, data: bytes) -> int:
    """PUT the file to a signed link, as the browser does; returns the HTTP status."""
    return httpx2.put(url, content=data, headers={"Content-Type": "video/mp4"}).status_code


def upload(client, account: Account, data: bytes | None = None) -> str:
    """Steps 1 and 2: ask for the links, PUT the file. Returns the object key."""
    answer = ask_upload_url(client, account).json()
    assert put_file(answer["put_url"], made_up_mp4() if data is None else data) == 200
    return answer["object_key"]


def confirm(client, account: Account, object_key: str, **body):
    """Step 3. The browser says 20 s and 2048 bytes unless told otherwise."""
    body = {"object_key": object_key, "duration_sec": 20, "size_bytes": 2048, **body}
    return client.post(
        "/api/media/intro-video/confirm",
        json={"content_type": "video/mp4", **body},
        headers=account.headers,
    )


def new_video(client, account: Account) -> int:
    """All three steps; returns the new video's id."""
    response = confirm(client, account, upload(client, account))
    assert response.status_code == 201
    return response.json()["id"]


def moderate(video_id: int, status: str = "approved") -> None:
    """What the moderation worker (BE-29) will do once it has checked the video."""
    sql("UPDATE intro_videos SET moderation_status = :s WHERE id = :id", s=status, id=video_id)


def action(client, account: Account, video_id: int, name: str):
    """POST /api/media/intro-video/<id>/<name>: post, unpost or delete."""
    return client.post(f"/api/media/intro-video/{video_id}/{name}", headers=account.headers)


def lifecycles(user_id: int) -> dict[int, str]:
    """{video id: lifecycle status} of one user's videos, as stored."""
    rows = sql("SELECT id, lifecycle_status FROM intro_videos WHERE user_id = :u", u=user_id)
    return dict(rows)


def error(code: int, detail: str) -> dict:
    return {"error": {"code": str(code), "detail": detail}}


# --- Step 1: upload-url -------------------------------------------------------------------


def test_upload_url_gives_my_own_key_and_links_signed_for_the_external_address(client, ana):
    response = ask_upload_url(client, ana, content_type="video/mp4", ext="mp4")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"object_key", "put_url", "get_url", "expires_sec", "max_bytes"}
    assert KEY_OF_USER_1.fullmatch(body["object_key"])
    assert (body["expires_sec"], body["max_bytes"]) == (900, 52_428_800)
    for link in (body["put_url"], body["get_url"]):
        assert link.startswith(f"{EXTERNAL}/{TEST_BUCKET}/{body['object_key']}?")
        query = parse_qs(urlparse(link).query)
        assert query["X-Amz-Expires"] == ["900"] and query["X-Amz-Signature"]


def test_every_upload_url_has_a_new_key(client, ana):
    keys = {ask_upload_url(client, ana).json()["object_key"] for _ in range(3)}
    assert len(keys) == 3


def test_upload_url_lifetime_is_60_to_3600_seconds(client, ana):
    link = ask_upload_url(client, ana, expires_sec=60).json()["put_url"]
    assert parse_qs(urlparse(link).query)["X-Amz-Expires"] == ["60"]
    for expires_sec in (59, 3601):
        assert ask_upload_url(client, ana, expires_sec=expires_sec).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"content_type": "video/webm"},
        {"content_type": "video/quicktime", "ext": "mov"},
        {"content_type": "image/png", "ext": "png"},
        {"ext": "exe"},
    ],
)
def test_upload_url_refuses_anything_but_mp4_with_415(client, ana, body):
    response = ask_upload_url(client, ana, **body)
    assert response.status_code == 415
    assert response.json() == error(415, "Only MP4 videos (video/mp4) are accepted")


def test_links_are_signed_for_the_public_https_address_without_connecting():
    # No service needed: nothing listens at 127.0.0.1:1, and signing never connects anywhere.
    storage = Storage(
        Settings(
            _env_file=None,
            minio_endpoint="127.0.0.1:1",
            minio_external_endpoint="https://localhost",
            minio_access_key="made-up-key",
            minio_secret_key="made-up-secret",
        )
    )
    link = storage.upload_url("users/7/intro/x.mp4", timedelta(seconds=60))
    assert link.startswith("https://localhost/files/users/7/intro/x.mp4?X-Amz-Algorithm=")
    assert "us-east-1" in parse_qs(urlparse(link).query)["X-Amz-Credential"][0]


# --- Steps 2 and 3: the PUT, then confirm --------------------------------------------------


def test_upload_put_and_confirm_save_a_pending_video_with_its_real_size(client, ana):
    object_key = upload(client, ana, made_up_mp4(4096))
    # The browser says 999 bytes; the file in storage has 4096.
    response = confirm(client, ana, object_key, duration_sec=12, size_bytes=999)
    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "moderation_status": "pending",
        "lifecycle_status": "loaded",
    }
    assert sql(
        "SELECT user_id, object_key, duration_sec, size_bytes, content_type, moderation_status,"
        " lifecycle_status, video_rating FROM intro_videos"
    ) == [(1, object_key, 12, 4096, "video/mp4", "pending", "loaded", "B")]


def test_each_confirm_queues_one_moderation_task(client, ana):
    first, second = upload(client, ana), upload(client, ana)
    assert confirm(client, ana, first).status_code == 201
    assert take_queued_tasks() == [(MODERATION_TASK, [1, first])]
    assert confirm(client, ana, second).status_code == 201
    assert take_queued_tasks() == [(MODERATION_TASK, [2, second])]


def test_confirm_refuses_another_users_key(client, ana, ben):
    bens_key = upload(client, ben)
    response = confirm(client, ana, bens_key)
    assert response.status_code == 400
    assert response.json() == error(400, "Invalid object_key: use the one upload-url gave you")
    assert sql("SELECT count(*) FROM intro_videos") == [(0,)]


@pytest.mark.parametrize(
    "object_key",
    [
        "users/1/intro/not-a-uuid.mp4",
        "users/1/intro/{uuid}.mov",
        "users/1/intro/{uuid}.mp4\n",  # a line break after the key
        "/users/1/intro/{uuid}.mp4",
        "users/1/intro/../2/intro/{uuid}.mp4",
        "users/12/intro/{uuid}.mp4",  # starts like user 1's prefix, but is user 12's
        "USERS/1/intro/{uuid}.mp4",
        "avatars/1/{uuid}.mp4",
    ],
)
def test_confirm_refuses_keys_that_upload_url_never_makes(client, ana, object_key):
    response = confirm(client, ana, object_key.format(uuid=uuid4()))
    assert response.status_code == 400


def test_confirm_refuses_a_key_with_no_uploaded_file(client, ana):
    object_key = ask_upload_url(client, ana).json()["object_key"]  # but no PUT
    response = confirm(client, ana, object_key)
    assert response.status_code == 400
    assert response.json() == error(
        400, "No uploaded file at this object_key: PUT the video to put_url first"
    )


def test_confirm_refuses_a_file_over_50_mib_even_when_the_browser_says_it_is_small(client, ana):
    object_key = upload(client, ana, made_up_mp4(MAX_SIZE_BYTES + 1))
    response = confirm(client, ana, object_key, size_bytes=1000)
    assert response.status_code == 413
    assert response.json() == error(413, "The video is larger than 50 MiB")
    assert sql("SELECT count(*) FROM intro_videos") == [(0,)]


def test_a_file_of_exactly_50_mib_is_accepted(client, ana):
    object_key = upload(client, ana, made_up_mp4(MAX_SIZE_BYTES))
    assert confirm(client, ana, object_key, size_bytes=MAX_SIZE_BYTES).status_code == 201
    assert sql("SELECT size_bytes FROM intro_videos") == [(52_428_800,)]


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"duration_sec": 31}, "body → duration_sec: Input should be less than or equal to 30"),
        ({"duration_sec": 0}, "body → duration_sec: Input should be greater than or equal to 1"),
        (
            {"size_bytes": MAX_SIZE_BYTES + 1},
            "body → size_bytes: Input should be less than or equal to 52428800",
        ),
        ({"content_type": "video/webm"}, "body → content_type: Input should be 'video/mp4'"),
    ],
)
def test_confirm_refuses_a_video_said_to_be_too_long_or_too_big(client, ana, body, detail):
    response = confirm(client, ana, upload(client, ana), **body)
    assert response.status_code == 422
    assert response.json() == error(422, detail)


@pytest.mark.parametrize(
    "data",
    [
        b"\x89PNG\r\n\x1a\n" + bytes(100),  # a PNG image
        b"just some text, named .mp4",
        b"",  # an empty file
    ],
)
def test_confirm_refuses_a_file_that_is_not_an_mp4_whatever_its_name(client, ana, data):
    response = confirm(client, ana, upload(client, ana, data))
    assert response.status_code == 415
    assert response.json() == error(415, "The uploaded file is not an MP4 video")


def test_a_fourth_video_is_refused_until_one_is_deleted(client, ana):
    first = new_video(client, ana)
    new_video(client, ana)
    new_video(client, ana)
    response = confirm(client, ana, upload(client, ana))
    assert response.status_code == 409
    assert response.json() == error(409, "You already have 3 videos: delete one to add a new one")
    # Posted and unposted videos count too; only deleted ones do not.
    assert action(client, ana, first, "delete").status_code == 200
    assert confirm(client, ana, upload(client, ana)).status_code == 201
    assert sorted(lifecycles(ana.id).values()) == ["deleted", "loaded", "loaded", "loaded"]


def test_the_same_file_cannot_be_confirmed_twice_even_after_a_delete(client, ana):
    object_key = upload(client, ana)
    video_id = confirm(client, ana, object_key).json()["id"]
    assert confirm(client, ana, object_key).json() == error(409, "This video is already confirmed")
    action(client, ana, video_id, "delete")
    assert confirm(client, ana, object_key).status_code == 409
    assert sql("SELECT count(*) FROM intro_videos") == [(1,)]
    assert take_queued_tasks() == [(MODERATION_TASK, [video_id, object_key])]


def test_a_refused_confirm_queues_nothing(client, ana, ben):
    confirm(client, ana, upload(client, ben))  # not her key
    confirm(client, ana, ask_upload_url(client, ana).json()["object_key"])  # no file
    confirm(client, ana, upload(client, ana, b"not a video"))  # not an MP4
    assert take_queued_tasks() == []


@contextmanager
def captured_logs() -> Iterator[list[dict]]:
    """The JSON log lines written inside the `with` block, as dicts."""
    stream = io.StringIO()
    handler = json_handler(stream)
    logging.getLogger().addHandler(handler)
    lines: list[dict] = []
    try:
        yield lines
    finally:
        logging.getLogger().removeHandler(handler)
        lines.extend(json.loads(line) for line in stream.getvalue().splitlines())


def test_when_the_queue_is_down_confirm_still_saves_the_video_and_logs_it(client, ana):
    object_key = upload(client, ana)
    # Nothing listens on port 1: like the redis container being stopped.
    with (
        TestClient(media_app(redis_url="redis://127.0.0.1:1/0")) as no_queue,
        captured_logs() as logs,
    ):
        started = time.monotonic()
        response = confirm(no_queue, ana, object_key)
        seconds = time.monotonic() - started
    assert response.status_code == 201
    assert sql("SELECT moderation_status, lifecycle_status FROM intro_videos") == [
        ("pending", "loaded")
    ]
    [line] = [line for line in logs if line["event"] == "moderation task not queued"]
    assert (line["level"], line["video_id"]) == ("error", 1)
    assert seconds < 5


# --- post, unpost, delete -----------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending", "rejected", "moderation_error"])
def test_only_an_approved_video_can_be_posted(client, ana, status):
    video_id = new_video(client, ana)
    moderate(video_id, status)
    response = action(client, ana, video_id, "post")
    assert response.status_code == 409
    assert response.json() == error(409, "Only a video approved by moderation can be posted")
    assert lifecycles(ana.id) == {video_id: "loaded"}


def test_an_approved_video_is_posted(client, ana):
    video_id = new_video(client, ana)
    moderate(video_id)
    response = action(client, ana, video_id, "post")
    assert response.status_code == 200
    expected = {"id": video_id, "moderation_status": "approved", "lifecycle_status": "posted"}
    assert response.json() == expected
    assert lifecycles(ana.id) == {video_id: "posted"}


def test_posting_a_video_unposts_my_previous_one(client, ana):
    first, second = new_video(client, ana), new_video(client, ana)
    moderate(first)
    moderate(second)
    action(client, ana, first, "post")
    assert action(client, ana, second, "post").json()["lifecycle_status"] == "posted"
    assert lifecycles(ana.id) == {first: "unposted", second: "posted"}
    assert action(client, ana, first, "post").status_code == 200
    assert lifecycles(ana.id) == {first: "posted", second: "unposted"}


def test_posting_a_posted_video_again_is_409(client, ana):
    video_id = new_video(client, ana)
    moderate(video_id)
    action(client, ana, video_id, "post")
    assert action(client, ana, video_id, "post").json() == error(
        409, "This video is already posted"
    )


def test_a_posted_video_can_be_unposted_then_posted_again(client, ana):
    video_id = new_video(client, ana)
    moderate(video_id)
    action(client, ana, video_id, "post")
    response = action(client, ana, video_id, "unpost")
    assert response.status_code == 200
    assert response.json()["lifecycle_status"] == "unposted"
    assert action(client, ana, video_id, "post").json()["lifecycle_status"] == "posted"


def test_unpost_needs_a_posted_video(client, ana):
    video_id = new_video(client, ana)
    response = action(client, ana, video_id, "unpost")
    assert response.status_code == 409
    assert response.json() == error(409, "This video is not posted")


def test_delete_is_a_soft_delete(client, ana):
    object_key = upload(client, ana)
    video_id = confirm(client, ana, object_key).json()["id"]
    moderate(video_id)
    action(client, ana, video_id, "post")
    response = action(client, ana, video_id, "delete")
    assert response.status_code == 200
    expected = {"id": video_id, "moderation_status": "approved", "lifecycle_status": "deleted"}
    assert response.json() == expected
    # The row and the file stay; the video is only marked "deleted".
    assert lifecycles(ana.id) == {video_id: "deleted"}
    assert minio_client().stat_object(TEST_BUCKET, object_key).size == 2048
    # From now on it is gone for me: not in my list, and every action is 404.
    assert client.get("/api/media/intro-video/mine", headers=ana.headers).json()["items"] == []
    for name in ("post", "unpost", "delete"):
        assert action(client, ana, video_id, name).json() == error(404, "Video not found")


@pytest.mark.parametrize("name", ["post", "unpost", "delete"])
def test_nobody_can_change_another_users_video(client, ana, ben, name):
    video_id = new_video(client, ben)
    moderate(video_id)
    action(client, ben, video_id, "post")
    response = action(client, ana, video_id, name)
    # The same 404 as a video that does not exist: Ana cannot even tell it is there.
    assert response.json() == error(404, "Video not found")
    assert lifecycles(ben.id) == {video_id: "posted"}
    assert action(client, ana, 999, name).json() == error(404, "Video not found")


# --- mine --------------------------------------------------------------------------------


def test_mine_lists_only_my_videos_newest_first_without_the_deleted_one(client, ana, ben):
    first, second, third = (new_video(client, ana) for _ in range(3))
    new_video(client, ben)
    action(client, ana, second, "delete")
    response = client.get("/api/media/intro-video/mine", headers=ana.headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [third, first]
    assert set(items[0]) == {
        "id",
        "object_key",
        "duration_sec",
        "size_bytes",
        "content_type",
        "moderation_status",
        "lifecycle_status",
        "created_at",
        "updated_at",
        "signed_url",
        "expires_sec",
    }
    assert items[0]["moderation_status"] == "pending"
    assert items[0]["created_at"].endswith("Z")  # UTC, with the time zone


def test_mine_signed_url_downloads_my_file(client, ana):
    data = made_up_mp4(3000)
    confirm(client, ana, upload(client, ana, data))
    [item] = client.get("/api/media/intro-video/mine?expires_sec=120", headers=ana.headers).json()[
        "items"
    ]
    assert item["expires_sec"] == 120
    assert parse_qs(urlparse(item["signed_url"]).query)["X-Amz-Expires"] == ["120"]
    download = httpx2.get(item["signed_url"])
    assert (download.status_code, download.content) == (200, data)
    # Without the signature the bucket refuses it: the videos are private.
    assert httpx2.get(item["signed_url"].split("?")[0]).status_code == 403


# --- the feed ----------------------------------------------------------------------------


def add_video(user_id: int, moderation: str = "approved", lifecycle: str = "posted", **row) -> int:
    """A video row added straight to the database (no file), for the feed tests."""
    [(video_id,)] = sql(
        "INSERT INTO intro_videos (user_id, object_key, duration_sec, size_bytes, content_type,"
        " moderation_status, lifecycle_status, video_rating)"
        " VALUES (:user_id, :key, 25, 1000, 'video/mp4', :moderation, :lifecycle, :rating)"
        " RETURNING id",
        user_id=user_id,
        key=f"users/{user_id}/intro/{uuid4()}.mp4",
        moderation=moderation,
        lifecycle=lifecycle,
        rating=row.get("rating", "B"),
    )
    return video_id


def feed(client, account: Account, **query) -> dict:
    response = client.get("/api/media/feed", params=query, headers=account.headers)
    assert response.status_code == 200
    return response.json()


def feed_ids(client, account: Account, **query) -> list[int]:
    return [item["id"] for item in feed(client, account, **query)["items"]]


def whole_feed(client, account: Account, **query) -> list[int]:
    """Every page, following next_cursor until it is null."""
    ids, cursor = [], None
    while True:
        page = (
            feed(client, account, **query, cursor=cursor)
            if cursor
            else feed(client, account, **query)
        )
        ids += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            return ids


def make_company_with_job(owner: Account, title: str = "Barista") -> int:
    """The owner becomes an employer: an active company with one open job. Returns the job id."""
    sql("INSERT INTO companies (owner_user_id, name) VALUES (:u, 'Cafe')", u=owner.id)
    [(job_id,)] = sql(
        "INSERT INTO jobs (owner_id, title, description, latitude, longitude, location, status)"
        " SELECT id, :title, 'Coffee all day', 25.2, 55.3, 'Abu Dhabi', 'open' FROM companies"
        " WHERE owner_user_id = :u RETURNING id",
        title=title,
        u=owner.id,
    )
    return job_id


def apply(job_id: int, applicant: Account, status: str = "submitted") -> None:
    sql(
        "INSERT INTO applications (job_id, applicant_id, company_id, status)"
        " SELECT :job_id, :applicant, owner_id, :status FROM jobs WHERE id = :job_id",
        job_id=job_id,
        applicant=applicant.id,
        status=status,
    )


def test_the_feed_shows_only_approved_and_posted_videos(client, ana, ben):
    shown = add_video(ben.id)
    add_video(ben.id, "approved", "unposted")
    add_video(ben.id, "approved", "deleted")
    add_video(ana.id, "approved", "loaded")
    add_video(ana.id, "pending", "loaded")
    add_video(ana.id, "rejected", "loaded")
    assert feed_ids(client, ana) == [shown]


def test_a_feed_item_has_its_author_and_a_link_that_downloads_the_file(client, ana, ben):
    data = made_up_mp4(5000)
    video_id = confirm(client, ana, upload(client, ana, data), duration_sec=17).json()["id"]
    moderate(video_id)
    action(client, ana, video_id, "post")
    [item] = feed(client, ben, expires_sec=60)["items"]
    signed_url = item.pop("signed_url")
    assert item == {
        "id": video_id,
        "user_id": ana.id,
        "duration_sec": 17,
        "size_bytes": 5000,
        "content_type": "video/mp4",
        "expires_sec": 60,
        "created_at": item["created_at"],
        "author_name": "Ana Silva",
        "author_position": "Barista",
    }
    assert signed_url.startswith(f"{EXTERNAL}/{TEST_BUCKET}/users/{ana.id}/intro/")
    download = httpx2.get(signed_url)
    assert (download.status_code, download.content) == (200, data)


def test_the_feed_hides_the_videos_of_deleted_accounts(client, ana, ben):
    add_video(ben.id)
    client.delete("/api/users/me", headers=ben.headers)
    assert feed_ids(client, ana) == []


def test_the_feed_is_newest_first_and_pages_follow_next_cursor(client, ana):
    # One posted video per user (the database allows no more), so five users.
    ids = [add_video(add_user(f"user{number}@example.com")) for number in range(5)]
    first_page = feed(client, ana, limit=2)
    assert [item["id"] for item in first_page["items"]] == [ids[4], ids[3]]
    assert first_page["next_cursor"] == ids[3]
    assert whole_feed(client, ana, limit=2) == ids[::-1]
    # Exactly one full page: no next page, so next_cursor is null at once.
    assert feed(client, ana, limit=5)["next_cursor"] is None


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 51}, {"expires_sec": 30}])
def test_the_feed_refuses_a_bad_limit_or_lifetime(client, ana, query):
    response = client.get("/api/media/feed", params=query, headers=ana.headers)
    assert response.status_code == 422


def test_employers_see_only_videos_rated_a_or_b(client, ana):
    graded = {
        rating: add_video(add_user(f"{rating}@example.com"), rating=rating)
        for rating in ("A", "B", "C")
    }
    carla = make_user(client, "carla@example.com")
    make_company_with_job(carla)
    assert feed_ids(client, carla) == [graded["B"], graded["A"]]
    # A user with no company (a job seeker) sees all three.
    assert feed_ids(client, ana) == [graded["C"], graded["B"], graded["A"]]


def test_the_feed_for_a_job_shows_applicants_then_matching_positions_then_everyone(client):
    employer = make_user(client, "boss@example.com")
    job_id = make_company_with_job(employer, title="Barista")
    people = {
        name: make_user(client, f"{name}@example.com", position)
        for name, position in [
            ("applied", "Cook"),
            ("viewed", "Waiter"),
            ("matches", "Head barista"),
            ("trainee", "BARISTA trainee"),
            ("other", "Driver"),
            ("refused", "Cleaner"),
        ]
    }
    apply(job_id, people["applied"])
    apply(job_id, people["viewed"], "viewed")
    apply(job_id, people["refused"], "rejected")  # answered already: no longer first
    # Added in a mixed order, so the ids alone would give another order.
    video = {name: add_video(people[name].id) for name in sorted(people)}
    expected = [
        *sorted([video["viewed"], video["applied"]], reverse=True),  # 1. waiting applicants
        *sorted([video["trainee"], video["matches"]], reverse=True),  # 2. position matches
        *sorted([video["refused"], video["other"]], reverse=True),  # 3. everyone else
    ]
    assert feed_ids(client, employer, job_id=job_id) == expected
    # Page by page, the order is the same: no video is skipped or shown twice.
    assert whole_feed(client, employer, job_id=job_id, limit=2) == expected
    assert whole_feed(client, employer, job_id=job_id, limit=4) == expected
    # Without job_id it is simply newest first; an unknown job gives the same order.
    assert feed_ids(client, employer) == sorted(video.values(), reverse=True)
    assert feed_ids(client, employer, job_id=999) == sorted(video.values(), reverse=True)


# --- routes that need no service ------------------------------------------------------


MEDIA_ROUTES = [
    ("POST", "/api/media/intro-video/upload-url", {}),
    (
        "POST",
        "/api/media/intro-video/confirm",
        {"object_key": "x", "duration_sec": 5, "size_bytes": 10, "content_type": "video/mp4"},
    ),
    ("GET", "/api/media/intro-video/mine", None),
    ("POST", "/api/media/intro-video/1/post", None),
    ("POST", "/api/media/intro-video/1/unpost", None),
    ("POST", "/api/media/intro-video/1/delete", None),
    ("GET", "/api/media/feed", None),
]


@pytest.mark.parametrize(("method", "path", "body"), MEDIA_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not.a.token"}])
def test_every_media_route_needs_a_valid_access_token(method, path, body, headers):
    with TestClient(build_app()) as test_client:
        response = test_client.request(method, path, json=body, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/media/intro-video/draft/upload-url"),
        ("POST", "/api/media/intro-video/draft/confirm"),
        ("GET", "/api/media/feed/demo"),
        ("GET", "/api/media/health"),
    ],
)
def test_draft_videos_the_demo_feed_and_media_health_are_not_ported(method, path):
    with TestClient(build_app()) as test_client:
        assert test_client.request(method, path).status_code == 404
