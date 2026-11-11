"""Avatars and company logos (/api/media/avatar/*, /api/media/company-logo/*) against a real
MinIO and PostgreSQL.

The pictures really go up to MinIO with an HTTP PUT, as the browser does, into the private
staging/ folder. confirm checks them and the server publishes a copy under avatars/ or logos/,
which come back down without any login, through the anonymous policy that minio-init sets on
the bucket (INF-04): anyone may download the files under avatars/ and logos/, and nothing else.
The users, the companies and the pictures are made up: a "picture" is a tiny red square that
Pillow draws here as a real JPEG, PNG or WebP file.

Like tests/test_media.py, these tests use only TEST_* variables and skip without them (its
docstring shows how to start the containers; Redis is not needed here). They empty the users
table (and every table that points at it) and the "pictures-test" bucket.
"""

import io
import json
import logging
import os
import re
import socket
import time
import zlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx2
import pytest
from conftest import DATABASE_SKIP_REASON, TEST_DATABASE_URL, alembic, build_app, sql
from fastapi.testclient import TestClient
from minio import Minio
from PIL import Image

from app.auth import security
from app.core.config import Settings
from app.core.logging import json_handler
from app.core.storage import Storage

TEST_MINIO_ENDPOINT = os.environ.get("TEST_MINIO_ENDPOINT", "")  # host:port, plain HTTP
TEST_MINIO_ACCESS_KEY = os.environ.get("TEST_MINIO_ACCESS_KEY", "")
TEST_MINIO_SECRET_KEY = os.environ.get("TEST_MINIO_SECRET_KEY", "")
TEST_BUCKET = "pictures-test"
# In the tests the browser reaches MinIO directly, so the addresses are made for it.
EXTERNAL = f"http://{TEST_MINIO_ENDPOINT}"
DEFAULT_AVATAR_URL = "/api/media/avatar/default.svg"

PASSWORD = "correct horse battery"
# Argon2 is slow on purpose, so the hash is made once and shared by every test user.
PASSWORD_HASH = security.hash_password(PASSWORD)

# Each picture type: Pillow's name for it, and the Content-Type a browser sends with it.
PILLOW_FORMAT = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}
CONTENT_TYPE = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
MAX_PICTURE_BYTES = 5 * 1024 * 1024
UUID = "[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}"
HTML = b"<html><script>alert(document.cookie)</script></html>"


def made_up_picture(ext: str = "png") -> bytes:
    """A real 8 x 8 picture of this type (a red square), drawn here with Pillow."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buffer, PILLOW_FORMAT[ext])
    return buffer.getvalue()


def png_chunk(kind: bytes, data: bytes) -> bytes:
    """One part ("chunk") of a PNG file: its length, its 4-letter kind, the data, and a
    checksum of the kind and the data."""
    return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")


# A PNG file starts with an 8-byte signature, then its IHDR chunk (25 bytes): width, height...
PNG_HEADER_END = 33


def png_of_exactly(size: int) -> bytes:
    """A real PNG of exactly `size` bytes: the red square, plus a private "paDd" chunk of
    zeros that picture readers skip."""
    png = made_up_picture("png")
    padding = bytes(size - len(png) - 12)  # 12 = the length, kind and checksum of the chunk
    return png[:PNG_HEADER_END] + png_chunk(b"paDd", padding) + png[PNG_HEADER_END:]


def png_claiming(width: int, height: int) -> bytes:
    """The red square, with a header that claims this size in pixels: a "decompression bomb"
    is a small file whose picture is huge."""
    png = made_up_picture("png")
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + png[24:29]
    return png[:8] + png_chunk(b"IHDR", header) + png[PNG_HEADER_END:]


def services_skip_reason() -> str | None:
    """Why these tests cannot run here, or None when they can."""
    if DATABASE_SKIP_REASON:
        return DATABASE_SKIP_REASON
    if not (TEST_MINIO_ENDPOINT and TEST_MINIO_ACCESS_KEY and TEST_MINIO_SECRET_KEY):
        return "TEST_MINIO_ENDPOINT, TEST_MINIO_ACCESS_KEY or TEST_MINIO_SECRET_KEY is not set"
    host, port = TEST_MINIO_ENDPOINT.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        return f"nothing answers at {TEST_MINIO_ENDPOINT}"
    return None


def minio_client() -> Minio:
    """Our own MinIO client, to look into the test bucket."""
    return Minio(
        TEST_MINIO_ENDPOINT,
        access_key=TEST_MINIO_ACCESS_KEY,
        secret_key=TEST_MINIO_SECRET_KEY,
        secure=False,
    )


def public_download_policy(bucket: str) -> str:
    """The anonymous policy of infra/minio/init-bucket.sh (INF-04): anyone may download the
    files under avatars/ and logos/ (s3:GetObject); no listing, no upload, nothing else."""
    statement = {
        "Effect": "Allow",
        "Principal": {"AWS": ["*"]},
        "Action": ["s3:GetObject"],
        "Resource": [f"arn:aws:s3:::{bucket}/avatars/*", f"arn:aws:s3:::{bucket}/logos/*"],
    }
    return json.dumps({"Version": "2012-10-17", "Statement": [statement]})


def pictures_app(**overrides: object):
    """An app on the test database and the test bucket."""
    settings = {
        "database_url": TEST_DATABASE_URL,
        "minio_endpoint": TEST_MINIO_ENDPOINT,
        "minio_external_endpoint": EXTERNAL,
        "minio_bucket": TEST_BUCKET,
        "minio_access_key": TEST_MINIO_ACCESS_KEY,
        "minio_secret_key": TEST_MINIO_SECRET_KEY,
        **overrides,
    }
    return build_app(**settings)


@pytest.fixture(scope="module")
def services():
    """Skip without the services; otherwise bring the schema up and set the bucket up as
    minio-init does: private, with anonymous download under avatars/ and logos/."""
    reason = services_skip_reason()
    if reason:
        pytest.skip(reason)
    alembic("upgrade", "head")
    minio = minio_client()
    if not minio.bucket_exists(TEST_BUCKET):
        minio.make_bucket(TEST_BUCKET)
    minio.set_bucket_policy(TEST_BUCKET, public_download_policy(TEST_BUCKET))


@pytest.fixture
def app(services):
    """This file's app. Each test starts with no users and an empty bucket."""
    # CASCADE also empties companies and every other table that points at users.
    sql("TRUNCATE users RESTART IDENTITY CASCADE")
    minio = minio_client()
    for stored in minio.list_objects(TEST_BUCKET, recursive=True):
        minio.remove_object(TEST_BUCKET, stored.object_name)
    return pictures_app()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


class Account(NamedTuple):
    id: int
    headers: dict  # {"Authorization": "Bearer <access token>"}


def make_user(client, email: str) -> Account:
    """A verified account added straight to the database, logged in through the real
    /api/auth/login."""
    [(user_id,)] = sql(
        "INSERT INTO users (email, password_hash, is_email_verified)"
        " VALUES (:email, :hash, true) RETURNING id",
        email=email,
        hash=PASSWORD_HASH,
    )
    tokens = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()
    return Account(user_id, {"Authorization": f"Bearer {tokens['access_token']}"})


@pytest.fixture
def ana(client) -> Account:
    return make_user(client, "ana@example.com")


@pytest.fixture
def ben(client) -> Account:
    return make_user(client, "ben@example.com")


def make_company(owner: Account, status: str = "active") -> int:
    """The owner becomes an employer: a company of theirs. Returns its id."""
    [(company_id,)] = sql(
        "INSERT INTO companies (owner_user_id, name, status) VALUES (:u, 'Cafe', :status)"
        " RETURNING id",
        u=owner.id,
        status=status,
    )
    return company_id


def ask_upload_url(client, account: Account, kind: str = "avatar", **query):
    """Step 1: POST /api/media/avatar/upload-url or /api/media/company-logo/upload-url."""
    return client.post(f"/api/media/{kind}/upload-url", params=query, headers=account.headers)


def put_file(url: str, data: bytes, content_type: str | None) -> int:
    """Step 2: PUT the file to a signed link, as the browser does; returns the HTTP status."""
    headers = {"Content-Type": content_type} if content_type else {}
    return httpx2.put(url, content=data, headers=headers).status_code


def upload(
    client,
    account: Account,
    kind: str = "avatar",
    ext: str = "png",
    data: bytes | None = None,
    content_type: str | None = "auto",
) -> str:
    """Steps 1 and 2: ask for the link, PUT the file. Returns the object key (in staging/). By
    default the file is a small picture of type ext, sent with that type's Content-Type
    ("auto", as the browser does); content_type=None sends no Content-Type at all."""
    answer = ask_upload_url(client, account, kind, ext=ext).json()
    data = made_up_picture(ext) if data is None else data
    content_type = CONTENT_TYPE[ext] if content_type == "auto" else content_type
    assert put_file(answer["put_url"], data, content_type) == 200
    return answer["object_key"]


def confirm(client, account: Account, object_key: str, kind: str = "avatar"):
    """Step 3: POST /api/media/avatar/confirm or /api/media/company-logo/confirm."""
    return client.post(
        f"/api/media/{kind}/confirm", json={"object_key": object_key}, headers=account.headers
    )


def publish(client, account: Account, kind: str = "avatar", ext: str = "png") -> str:
    """Steps 1 to 3 with a good picture. Returns the key of its public copy."""
    assert confirm(client, account, upload(client, account, kind, ext), kind).status_code == 204
    if kind == "avatar":
        return avatar_in_db(account.id)
    [(key,)] = sql(
        "SELECT logo_object_key FROM companies WHERE owner_user_id = :u AND status = 'active'",
        u=account.id,
    )
    return key


def put_straight_into_storage(object_key: str, data: bytes, content_type: str) -> None:
    """A file at any key, written with our own MinIO client: upload-url would never make
    such a key, but confirm must refuse it even when a file is there."""
    minio_client().put_object(
        TEST_BUCKET, object_key, io.BytesIO(data), len(data), content_type=content_type
    )


def is_stored(object_key: str) -> bool:
    return any(minio_client().list_objects(TEST_BUCKET, prefix=object_key))


def stored_keys(folder: str) -> list[str]:
    """Every file under this folder of the test bucket, e.g. "avatars/1/"."""
    found = minio_client().list_objects(TEST_BUCKET, prefix=folder, recursive=True)
    return [stored.object_name for stored in found]


def public_address(object_key: str) -> str:
    """The plain address of a file, with no signature: what anyone on the internet can ask."""
    return f"{EXTERNAL}/{TEST_BUCKET}/{object_key}"


def avatar_in_db(user_id: int) -> str | None:
    [(key,)] = sql("SELECT avatar_object_key FROM users WHERE id = :id", id=user_id)
    return key


def logo_in_db(company_id: int) -> str | None:
    [(key,)] = sql("SELECT logo_object_key FROM companies WHERE id = :id", id=company_id)
    return key


def my_avatar_url(client, account: Account) -> str:
    response = client.get("/api/users/me", headers=account.headers)
    assert response.status_code == 200
    return response.json()["avatar_url"]


def error(code: int, detail: str) -> dict:
    return {"error": {"code": str(code), "detail": detail}}


NOT_YOUR_KEY = error(400, "Invalid object_key: use the one upload-url gave you")
ONLY_PICTURES = error(415, "Only jpg, png or webp pictures are accepted")
NO_PICTURE = error(400, "No uploaded file at this object_key: PUT the picture to put_url first")
NO_COMPANY = error(404, "You have no company")
TOO_MANY_PIXELS = error(413, "The picture has more than 25 million pixels")


# --- Step 1: upload-url -------------------------------------------------------------------


def test_avatar_upload_url_gives_a_private_staging_key_and_a_signed_put_link(client, ana):
    response = ask_upload_url(client, ana, ext="webp")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"object_key", "put_url", "expires_sec", "max_bytes"}
    # The upload goes to staging/, never into the public avatars/ folder.
    assert re.fullmatch(rf"staging/avatars/{ana.id}/{UUID}\.webp", body["object_key"])
    assert (body["expires_sec"], body["max_bytes"]) == (900, MAX_PICTURE_BYTES)
    assert body["put_url"].startswith(f"{public_address(body['object_key'])}?")
    query = parse_qs(urlparse(body["put_url"]).query)
    assert query["X-Amz-Expires"] == ["900"] and query["X-Amz-Signature"]


def test_upload_url_is_jpg_by_default_and_takes_capital_letters(client, ana):
    assert ask_upload_url(client, ana).json()["object_key"].endswith(".jpg")
    assert ask_upload_url(client, ana, ext="PNG").json()["object_key"].endswith(".png")
    assert ask_upload_url(client, ana, expires_sec=60).json()["expires_sec"] == 60


@pytest.mark.parametrize("ext", ["gif", "svg", "jpeg", "mp4", "html", "", "png.html"])
def test_upload_url_refuses_extensions_other_than_jpg_png_webp(client, ana, ext):
    response = ask_upload_url(client, ana, ext=ext)
    assert (response.status_code, response.json()) == (415, ONLY_PICTURES)


@pytest.mark.parametrize("expires_sec", [59, 3601])
def test_upload_url_lifetime_is_60_to_3600_seconds(client, ana, expires_sec):
    assert ask_upload_url(client, ana, expires_sec=expires_sec).status_code == 422


# --- Steps 2 and 3: the PUT, then confirm -------------------------------------------------


@pytest.mark.parametrize("ext", ["jpg", "png", "webp"])
def test_a_confirmed_avatar_is_published_at_a_new_key_anyone_can_download(client, ana, ext):
    data = made_up_picture(ext)
    staging_key = upload(client, ana, ext=ext, data=data)
    response = confirm(client, ana, staging_key)
    assert (response.status_code, response.content) == (204, b"")
    # The server wrote a copy in the public folder, under a name of its own...
    public_key = avatar_in_db(ana.id)
    assert re.fullmatch(rf"avatars/{ana.id}/{UUID}\.{ext}", public_key)
    assert public_key.rsplit("/", 1)[-1] != staging_key.rsplit("/", 1)[-1]
    # ...and the upload itself is gone.
    assert not is_stored(staging_key)
    # A plain address in the public folder: no signature, so it never expires.
    avatar_url = my_avatar_url(client, ana)
    assert avatar_url == public_address(public_key)
    # Downloaded with no login and no signature, as an <img> on any page does.
    download = httpx2.get(avatar_url)
    assert (download.status_code, download.content) == (200, data)
    assert download.headers["content-type"] == CONTENT_TYPE[ext]


@pytest.mark.parametrize("content_type", ["text/html", "image/jpeg", None])
def test_the_public_copy_gets_the_content_type_the_server_checked(client, ana, content_type):
    # Whatever Content-Type the upload had (none at all is stored as
    # application/octet-stream), the public copy is served as the picture it really is.
    staging_key = upload(client, ana, ext="png", content_type=content_type)
    assert confirm(client, ana, staging_key).status_code == 204
    download = httpx2.get(my_avatar_url(client, ana))
    assert (download.status_code, download.headers["content-type"]) == (200, "image/png")


def test_without_an_avatar_avatar_url_is_the_default_picture_anyone_can_load(client, ana):
    assert avatar_in_db(ana.id) is None
    assert my_avatar_url(client, ana) == DEFAULT_AVATAR_URL
    # No Authorization header: the default picture needs no login either.
    response = client.get(DEFAULT_AVATAR_URL)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.content.startswith(b"<svg")


def test_patch_answers_with_avatar_url_too_and_cannot_set_it(client, ana):
    public_key = publish(client, ana)
    response = client.patch("/api/users/me", json={"bio": "Hi"}, headers=ana.headers)
    assert response.json()["avatar_url"] == public_address(public_key)
    # Only confirm changes the picture: PATCH refuses the field, like avatar_object_key.
    response = client.patch(
        "/api/users/me", json={"avatar_url": "https://example.com/x.png"}, headers=ana.headers
    )
    assert response.status_code == 422
    assert avatar_in_db(ana.id) == public_key


def test_the_default_avatar_comes_from_default_avatar_url(services, ana):
    other = "https://cdn.example.com/no-picture.png"
    with TestClient(pictures_app(default_avatar_url=other)) as client:
        assert my_avatar_url(client, ana) == other


def test_storage_turns_a_key_into_its_public_address():
    storage = Storage(
        Settings(minio_external_endpoint="https://localhost:8443", minio_bucket="files")
    )
    key = "avatars/12/0b6f3c52-0f6e-4c9a-9a3f-2f7d6c1e8a41.png"
    assert storage.avatar_url(key) == f"https://localhost:8443/files/{key}"
    assert storage.avatar_url(None) == DEFAULT_AVATAR_URL
    # A company with no logo has none, not a default one.
    logo = "logos/3/0b6f3c52-0f6e-4c9a-9a3f-2f7d6c1e8a41.webp"
    assert storage.logo_url(logo) == f"https://localhost:8443/files/{logo}"
    assert storage.logo_url(None) is None


# --- Nothing that was not checked is ever public ---------------------------------------------


def test_an_upload_cannot_be_downloaded_before_confirm(client, ana):
    for data, content_type in [(made_up_picture("png"), "image/png"), (HTML, "text/html")]:
        staging_key = upload(client, ana, data=data, content_type=content_type)
        assert is_stored(staging_key)
        # No login, no signature: staging/ is not one of the public folders.
        assert httpx2.get(public_address(staging_key)).status_code == 403
    assert stored_keys("avatars/") == []


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (HTML, "text/html"),
        (b"just some text", "text/plain"),
        (b"\x89PNG\r\n\x1a\n" + HTML, "text/html"),  # starts like a PNG, then a web page
    ],
)
def test_a_refused_upload_is_never_served_and_is_deleted(client, ana, data, content_type):
    staging_key = upload(client, ana, ext="png", data=data, content_type=content_type)
    assert httpx2.get(public_address(staging_key)).status_code == 403
    response = confirm(client, ana, staging_key)
    assert (response.status_code, response.json()) == (
        415,
        error(415, "The uploaded file is not a png picture"),
    )
    assert not is_stored(staging_key)
    assert stored_keys(f"avatars/{ana.id}/") == []
    assert avatar_in_db(ana.id) is None


def test_an_old_upload_link_cannot_change_the_published_picture(client, ana):
    answer = ask_upload_url(client, ana, ext="png").json()
    data = made_up_picture("png")
    assert put_file(answer["put_url"], data, "image/png") == 200
    assert confirm(client, ana, answer["object_key"]).status_code == 204
    public_key = avatar_in_db(ana.id)
    # The link still works until it expires, but only into the private staging folder...
    assert put_file(answer["put_url"], HTML, "text/html") == 200
    assert httpx2.get(public_address(answer["object_key"])).status_code == 403
    # ...so the published picture is unchanged...
    download = httpx2.get(public_address(public_key))
    assert (download.status_code, download.content) == (200, data)
    assert download.headers["content-type"] == "image/png"
    # ...and confirming that key again refuses (and deletes) what is there now.
    assert confirm(client, ana, answer["object_key"]).status_code == 415
    assert not is_stored(answer["object_key"])
    assert avatar_in_db(ana.id) == public_key
    assert stored_keys(f"avatars/{ana.id}/") == [public_key]


def test_nobody_can_upload_into_the_public_folders_without_a_link(client, ana):
    make_company(ana)
    avatar = publish(client, ana)
    logo = publish(client, ana, "company-logo")
    put_url = ask_upload_url(client, ana, ext="png").json()["put_url"]
    signature = urlparse(put_url).query
    for public_key in (avatar, logo):
        new_key = f"{public_key.rsplit('/', 1)[0]}/{uuid4()}.png"
        for url in (
            public_address(public_key),  # replace a published picture
            public_address(new_key),  # add a new file
            f"{public_address(public_key)}?{signature}",  # with a staging link's signature
        ):
            assert put_file(url, HTML, "text/html") == 403
        assert not is_stored(new_key)
    for public_key in (avatar, logo):
        download = httpx2.get(public_address(public_key))
        assert (download.status_code, download.content) == (200, made_up_picture("png"))


def test_confirming_the_same_upload_twice_publishes_it_once(client, ana):
    staging_key = upload(client, ana)
    assert confirm(client, ana, staging_key).status_code == 204
    public_key = avatar_in_db(ana.id)
    response = confirm(client, ana, staging_key)
    assert (response.status_code, response.json()) == (400, NO_PICTURE)
    assert avatar_in_db(ana.id) == public_key
    assert stored_keys(f"avatars/{ana.id}/") == [public_key]


@pytest.mark.parametrize("kind", ["avatar", "company-logo"])
def test_two_confirms_of_the_same_upload_at_once_publish_it_once(app, client, ana, kind):
    folder = f"avatars/{ana.id}/"
    if kind == "company-logo":
        folder = f"logos/{make_company(ana)}/"
    staging_key = upload(client, ana, kind)
    read = app.state.storage.read

    def slow_read(key: str, max_bytes: int) -> bytes | None:
        data = read(key, max_bytes)
        time.sleep(0.3)  # the other confirm arrives while this one has read the upload
        return data

    app.state.storage.read = slow_read
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda _: confirm(client, ana, staging_key, kind), range(2)))
    # The second one waited for the first (the lock on my row, or my company's), then found
    # no upload.
    assert sorted(answer.status_code for answer in answers) == [204, 400]
    assert len(stored_keys(folder)) == 1


# --- What confirm refuses ----------------------------------------------------------------


def test_nobody_can_take_another_users_picture(client, ana, ben):
    bens_avatar = publish(client, ben)
    bens_upload = upload(client, ben)
    for object_key in (bens_avatar, bens_upload):
        response = confirm(client, ana, object_key)
        assert (response.status_code, response.json()) == (400, NOT_YOUR_KEY)
    assert avatar_in_db(ana.id) is None
    # Ben's avatar, his upload and their files are untouched.
    assert avatar_in_db(ben.id) == bens_avatar
    assert is_stored(bens_avatar) and is_stored(bens_upload)


@pytest.mark.parametrize(
    "object_key",
    [
        "avatars/1/{uuid}.png",  # my own public folder: only uploads in staging/ are confirmed
        "staging/avatars/2/{uuid}.png",  # Ben's staging folder (Ana is user 1)
        "staging/logos/1/{uuid}.png",  # a logo folder, not an avatar one
        "avatars/2/{uuid}.png",
        "users/1/intro/{uuid}.png",  # the private video folder
        "staging/avatars/1/../2/{uuid}.png",
        "staging/avatars/1/x/{uuid}.png",
        "staging/1/{uuid}.png",
        "/staging/avatars/1/{uuid}.png",
        "files/staging/avatars/1/{uuid}.png",
        "staging/avatars/01/{uuid}.png",
        "Staging/avatars/1/{uuid}.png",
        "staging/Avatars/1/{uuid}.png",
        "staging/avatars/1/not-a-uuid.png",
        "staging/avatars/1/{uuid}.jpg.png",
    ],
)
def test_confirm_refuses_any_key_outside_my_staging_folder_even_with_a_file_there(
    client, ana, object_key
):
    object_key = object_key.format(uuid=uuid4())
    written = ".." not in object_key  # the MinIO client itself refuses to write a ".." key
    if written:
        put_straight_into_storage(object_key, made_up_picture("png"), "image/png")
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (400, NOT_YOUR_KEY)
    assert avatar_in_db(ana.id) is None
    if written:  # a file that is not mine is never deleted by my confirm
        assert is_stored(object_key.lstrip("/"))  # MinIO drops a leading "/"


@pytest.mark.parametrize("ext", ["gif", "svg", "jpeg", "mp4", "html", "PNG", "png "])
def test_confirm_refuses_extensions_other_than_jpg_png_webp_even_with_a_file_there(
    client, ana, ext
):
    object_key = f"staging/avatars/{ana.id}/{uuid4()}.{ext}"
    put_straight_into_storage(object_key, made_up_picture("png"), "image/png")
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (415, ONLY_PICTURES)
    assert avatar_in_db(ana.id) is None


def test_confirm_refuses_a_key_with_no_extension(client, ana):
    response = confirm(client, ana, f"staging/avatars/{ana.id}/{uuid4()}")
    assert (response.status_code, response.json()) == (415, ONLY_PICTURES)


def test_confirm_refuses_a_key_with_no_uploaded_file(client, ana):
    object_key = ask_upload_url(client, ana, ext="png").json()["object_key"]  # no PUT
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (400, NO_PICTURE)
    assert avatar_in_db(ana.id) is None


@pytest.mark.parametrize(
    ("ext", "data"),
    [
        ("png", HTML),
        ("png", b"\x89PNG\r\n\x1a\n" + HTML),  # only starts like a PNG
        ("png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(100)),  # a PNG header, no picture
        ("png", made_up_picture("jpg")),  # a JPEG called .png
        ("jpg", made_up_picture("png")),  # a PNG called .jpg
        ("webp", made_up_picture("png")),
        ("jpg", made_up_picture("jpg")[:300]),  # cut short
        ("webp", b"RIFF\x24\x00\x00\x00AVI LIST" + bytes(100)),  # RIFF, but a video
        ("webp", b"\x00\x00\x00\x18ftypisom" + bytes(100)),  # an MP4
        ("png", b"\x89PNG"),
        ("jpg", b""),  # empty
    ],
)
def test_confirm_refuses_a_file_that_is_not_really_that_picture_type(client, ana, ext, data):
    staging_key = upload(client, ana, ext=ext, data=data)
    response = confirm(client, ana, staging_key)
    assert (response.status_code, response.json()) == (
        415,
        error(415, f"The uploaded file is not a {ext} picture"),
    )
    assert avatar_in_db(ana.id) is None
    assert not is_stored(staging_key) and stored_keys("avatars/") == []


def test_confirm_refuses_a_picture_over_5_mib(client, ana):
    staging_key = upload(client, ana, data=png_of_exactly(MAX_PICTURE_BYTES + 1))
    response = confirm(client, ana, staging_key)
    assert (response.status_code, response.json()) == (
        413,
        error(413, "The picture is larger than 5 MiB"),
    )
    assert avatar_in_db(ana.id) is None
    assert not is_stored(staging_key) and stored_keys("avatars/") == []


def test_a_picture_of_exactly_5_mib_is_accepted(client, ana):
    data = png_of_exactly(MAX_PICTURE_BYTES)
    assert len(data) == MAX_PICTURE_BYTES
    assert confirm(client, ana, upload(client, ana, data=data)).status_code == 204
    assert httpx2.get(my_avatar_url(client, ana)).content == data


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (6000, 5000),  # 30 million pixels: over our limit of 25 million
        (20000, 20000),  # 400 million: over Pillow's own limit too
    ],
)
def test_confirm_refuses_a_picture_of_too_many_pixels(client, ana, width, height):
    staging_key = upload(client, ana, data=png_claiming(width, height))
    response = confirm(client, ana, staging_key)
    assert (response.status_code, response.json()) == (413, TOO_MANY_PIXELS)
    assert avatar_in_db(ana.id) is None
    assert not is_stored(staging_key) and stored_keys("avatars/") == []


@pytest.mark.parametrize("body", [{}, {"object_key": "x" * 501}, {"object_key": None}])
def test_confirm_needs_an_object_key_of_at_most_500_characters(client, ana, body):
    response = client.post("/api/media/avatar/confirm", json=body, headers=ana.headers)
    assert response.status_code == 422


# --- A new picture replaces the old one ----------------------------------------------------


def test_a_new_avatar_deletes_the_old_file(client, ana, ben):
    bens_avatar = publish(client, ben)
    first = publish(client, ana, ext="jpg")
    first_url = my_avatar_url(client, ana)
    second = publish(client, ana, ext="webp")
    assert avatar_in_db(ana.id) == second
    assert stored_keys(f"avatars/{ana.id}/") == [second]
    assert not is_stored(first)
    # The old public link no longer gives the picture.
    assert httpx2.get(first_url).status_code == 404
    # Nobody else's file is touched.
    assert is_stored(bens_avatar)


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


def test_if_old_files_cannot_be_deleted_the_new_avatar_is_still_saved_and_logged(app, client, ana):
    first = publish(client, ana)
    staging_key = upload(client, ana)

    def remove_fails(key: str) -> None:
        raise ConnectionError("MinIO is down")

    # Only the deletes fail, on purpose: the checks before them still use the real MinIO.
    app.state.storage.remove = remove_fails
    with captured_logs() as logs:
        response = confirm(client, ana, staging_key)
    assert response.status_code == 204
    second = avatar_in_db(ana.id)
    assert second not in (first, None)
    # Both the upload and the old avatar are left behind, and both are logged.
    failed = [line for line in logs if line["event"] == "file not removed from storage"]
    assert {line["level"] for line in failed} == {"error"}
    assert sorted(line["object_key"] for line in failed) == sorted([staging_key, first])


# --- Company logos -------------------------------------------------------------------------


def test_an_employer_uploads_and_confirms_a_logo_that_anyone_can_download(client, ana):
    company_id = make_company(ana)
    data = made_up_picture("webp")
    answer = ask_upload_url(client, ana, "company-logo", ext="webp").json()
    assert re.fullmatch(rf"staging/logos/{company_id}/{UUID}\.webp", answer["object_key"])
    assert put_file(answer["put_url"], data, "image/webp") == 200
    assert httpx2.get(public_address(answer["object_key"])).status_code == 403
    response = confirm(client, ana, answer["object_key"], "company-logo")
    assert (response.status_code, response.content) == (204, b"")
    public_key = logo_in_db(company_id)
    assert re.fullmatch(rf"logos/{company_id}/{UUID}\.webp", public_key)
    assert not is_stored(answer["object_key"])
    assert sql("SELECT updated_by_id FROM companies") == [(ana.id,)]
    # logo_url, downloaded with no login.
    logo_url = pictures_app().state.storage.logo_url(public_key)
    assert logo_url == public_address(public_key)
    download = httpx2.get(logo_url)
    assert (download.status_code, download.content) == (200, data)
    assert download.headers["content-type"] == "image/webp"


@pytest.mark.parametrize("company", [None, "deleted"])
@pytest.mark.parametrize("step", ["upload-url", "confirm"])
def test_logo_routes_are_for_employers_only(client, ana, company, step):
    if company:
        make_company(ana, status=company)  # a deleted company counts as none
    if step == "upload-url":
        response = ask_upload_url(client, ana, "company-logo", ext="png")
    else:
        response = confirm(client, ana, f"staging/logos/1/{uuid4()}.png", "company-logo")
    assert (response.status_code, response.json()) == (404, NO_COMPANY)


def test_an_employer_cannot_use_another_companys_logo_or_an_avatar(client, ana, ben):
    make_company(ana)
    bens_company = make_company(ben)
    bens_logo = publish(client, ben, "company-logo")
    bens_upload = upload(client, ben, "company-logo")
    anas_avatar_upload = upload(client, ana)
    for object_key in (bens_logo, bens_upload, anas_avatar_upload):
        response = confirm(client, ana, object_key, "company-logo")
        assert (response.status_code, response.json()) == (400, NOT_YOUR_KEY)
        assert is_stored(object_key)
    assert logo_in_db(bens_company) == bens_logo


def test_the_logo_is_checked_like_an_avatar(client, ana):
    make_company(ana)
    response = ask_upload_url(client, ana, "company-logo", ext="gif")
    assert (response.status_code, response.json()) == (415, ONLY_PICTURES)
    object_key = upload(client, ana, "company-logo", data=b"GIF89a" + bytes(100))
    response = confirm(client, ana, object_key, "company-logo")
    assert response.json() == error(415, "The uploaded file is not a png picture")
    too_big = png_of_exactly(MAX_PICTURE_BYTES + 1)
    object_key = upload(client, ana, "company-logo", data=too_big)
    assert confirm(client, ana, object_key, "company-logo").status_code == 413
    assert stored_keys("logos/") == [] and stored_keys("staging/") == []


def test_a_new_logo_deletes_the_old_file(client, ana):
    company_id = make_company(ana)
    first = publish(client, ana, "company-logo")
    second = publish(client, ana, "company-logo", ext="jpg")
    assert logo_in_db(company_id) == second
    assert stored_keys(f"logos/{company_id}/") == [second]
    assert httpx2.get(public_address(first)).status_code == 404


# --- Deleting the account ------------------------------------------------------------------


def test_deleting_my_account_deletes_my_avatar_file_at_once(client, ana, ben):
    bens_avatar = publish(client, ben)
    public_key = publish(client, ana)
    avatar_url = my_avatar_url(client, ana)
    assert client.delete("/api/users/me", headers=ana.headers).status_code == 204
    assert not is_stored(public_key)
    assert httpx2.get(avatar_url).status_code == 404
    assert avatar_in_db(ana.id) is None
    # Ben's account and picture are untouched.
    assert avatar_in_db(ben.id) == bens_avatar and is_stored(bens_avatar)


def test_deleting_an_employers_account_deletes_the_company_logo_too(client, ana):
    company_id = make_company(ana)
    logo = publish(client, ana, "company-logo")
    assert client.delete("/api/users/me", headers=ana.headers).status_code == 204
    assert not is_stored(logo)
    assert logo_in_db(company_id) is None


def test_deleting_an_account_with_no_pictures_touches_no_file(client, ana, ben):
    bens_avatar = publish(client, ben)
    assert client.delete("/api/users/me", headers=ana.headers).status_code == 204
    assert sql("SELECT status FROM users WHERE id = :id", id=ana.id) == [("deleted",)]
    assert is_stored(bens_avatar)


# --- Routes that need no service -----------------------------------------------------------


PICTURE_ROUTES = [
    ("/api/media/avatar/upload-url", None),
    ("/api/media/avatar/confirm", {"object_key": "x"}),
    ("/api/media/company-logo/upload-url", None),
    ("/api/media/company-logo/confirm", {"object_key": "x"}),
]


@pytest.mark.parametrize(("path", "body"), PICTURE_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not.a.token"}])
def test_every_picture_route_needs_a_valid_access_token(path, body, headers):
    with TestClient(build_app()) as test_client:
        response = test_client.post(path, json=body, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_the_default_avatar_needs_no_service_and_no_login():
    with TestClient(build_app()) as test_client:
        response = test_client.get(DEFAULT_AVATAR_URL)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
