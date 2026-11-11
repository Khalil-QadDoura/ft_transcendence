"""Avatars and company logos (/api/media/avatar/*, /api/media/company-logo/*) against a real
MinIO and PostgreSQL.

The pictures really go up to MinIO with an HTTP PUT, as the browser does, and come back down
without any login, through the anonymous policy that minio-init sets on the bucket (INF-04):
anyone may download the files under avatars/ and logos/, and nothing else. The users, the
companies and the pictures are made up: a "picture" is a few bytes that start like a PNG, JPEG
or WebP file.

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
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx2
import pytest
from conftest import DATABASE_SKIP_REASON, TEST_DATABASE_URL, alembic, build_app, sql
from fastapi.testclient import TestClient
from minio import Minio

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

# The first bytes of real pictures of each type, and the Content-Type a browser sends with them.
PICTURE_START = {
    "jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01",
    "png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
    "webp": b"RIFF\x24\x00\x00\x00WEBPVP8 ",
}
CONTENT_TYPE = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
MAX_PICTURE_BYTES = 5 * 1024 * 1024
UUID = "[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}"


def made_up_picture(ext: str = "png", size: int = 1024) -> bytes:
    """A small made-up file that starts like a picture of this type; the rest is zeros."""
    return PICTURE_START[ext] + bytes(size - len(PICTURE_START[ext]))


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
    """Steps 1 and 2: ask for the link, PUT the file. Returns the object key. By default the
    file is a small picture of type ext, sent with that type's Content-Type ("auto", as the
    browser does); content_type=None sends no Content-Type at all."""
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


def put_straight_into_storage(object_key: str, data: bytes, content_type: str) -> None:
    """A file at any key, written with our own MinIO client: upload-url would never make
    such a key, but confirm must refuse it even when a file is there."""
    minio_client().put_object(
        TEST_BUCKET, object_key, io.BytesIO(data), len(data), content_type=content_type
    )


def is_stored(object_key: str) -> bool:
    return any(minio_client().list_objects(TEST_BUCKET, prefix=object_key))


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


# --- Step 1: upload-url -------------------------------------------------------------------


def test_avatar_upload_url_gives_a_key_in_my_public_folder_and_a_signed_put_link(client, ana):
    response = ask_upload_url(client, ana, ext="webp")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"object_key", "put_url", "expires_sec", "max_bytes"}
    assert re.fullmatch(rf"avatars/{ana.id}/{UUID}\.webp", body["object_key"])
    assert (body["expires_sec"], body["max_bytes"]) == (900, MAX_PICTURE_BYTES)
    assert body["put_url"].startswith(f"{EXTERNAL}/{TEST_BUCKET}/{body['object_key']}?")
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
def test_a_confirmed_avatar_is_in_user_out_and_anyone_can_download_it(client, ana, ext):
    data = made_up_picture(ext)
    object_key = upload(client, ana, ext=ext, data=data)
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.content) == (204, b"")
    assert avatar_in_db(ana.id) == object_key
    # A plain address in the public folder: no signature, so it never expires.
    avatar_url = my_avatar_url(client, ana)
    assert avatar_url == f"{EXTERNAL}/{TEST_BUCKET}/{object_key}"
    # Downloaded with no login and no signature, as an <img> on any page does.
    download = httpx2.get(avatar_url)
    assert (download.status_code, download.content) == (200, data)
    assert download.headers["content-type"] == CONTENT_TYPE[ext]


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
    object_key = upload(client, ana)
    confirm(client, ana, object_key)
    response = client.patch("/api/users/me", json={"bio": "Hi"}, headers=ana.headers)
    assert response.json()["avatar_url"] == f"{EXTERNAL}/{TEST_BUCKET}/{object_key}"
    # Only confirm changes the picture: PATCH refuses the field, like avatar_object_key.
    response = client.patch(
        "/api/users/me", json={"avatar_url": "https://example.com/x.png"}, headers=ana.headers
    )
    assert response.status_code == 422
    assert avatar_in_db(ana.id) == object_key


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
    # Ready for CompanyOut (BE-21): a company with no logo has none, not a default one.
    logo = "logos/3/0b6f3c52-0f6e-4c9a-9a3f-2f7d6c1e8a41.webp"
    assert storage.logo_url(logo) == f"https://localhost:8443/files/{logo}"
    assert storage.logo_url(None) is None


# --- What confirm refuses ----------------------------------------------------------------


def test_nobody_can_take_another_users_picture(client, ana, ben):
    bens_key = upload(client, ben)
    assert confirm(client, ben, bens_key).status_code == 204
    response = confirm(client, ana, bens_key)
    assert (response.status_code, response.json()) == (400, NOT_YOUR_KEY)
    assert avatar_in_db(ana.id) is None
    # Ben's avatar and its file are untouched.
    assert avatar_in_db(ben.id) == bens_key and is_stored(bens_key)


@pytest.mark.parametrize(
    "object_key",
    [
        "avatars/2/{uuid}.png",  # Ben's folder (Ana is user 1)
        "logos/1/{uuid}.png",  # a logo folder, not an avatar one
        "users/1/intro/{uuid}.png",  # the private video folder
        "avatars/1/../2/{uuid}.png",
        "avatars/1/x/{uuid}.png",
        "/avatars/1/{uuid}.png",
        "files/avatars/1/{uuid}.png",
        "avatars/01/{uuid}.png",
        "Avatars/1/{uuid}.png",
        "avatars/1/not-a-uuid.png",
        "avatars/1/{uuid}.jpg.png",
    ],
)
def test_confirm_refuses_any_key_outside_my_folder_even_with_a_file_there(client, ana, object_key):
    object_key = object_key.format(uuid=uuid4())
    if ".." not in object_key:  # the MinIO client itself refuses to write a ".." key
        put_straight_into_storage(object_key, made_up_picture("png"), "image/png")
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (400, NOT_YOUR_KEY)
    assert avatar_in_db(ana.id) is None


@pytest.mark.parametrize("ext", ["gif", "svg", "jpeg", "mp4", "html", "PNG", "png "])
def test_confirm_refuses_extensions_other_than_jpg_png_webp_even_with_a_file_there(
    client, ana, ext
):
    object_key = f"avatars/{ana.id}/{uuid4()}.{ext}"
    put_straight_into_storage(object_key, made_up_picture("png"), "image/png")
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (415, ONLY_PICTURES)
    assert avatar_in_db(ana.id) is None


def test_confirm_refuses_a_key_with_no_extension(client, ana):
    response = confirm(client, ana, f"avatars/{ana.id}/{uuid4()}")
    assert (response.status_code, response.json()) == (415, ONLY_PICTURES)


def test_confirm_refuses_a_key_with_no_uploaded_file(client, ana):
    object_key = ask_upload_url(client, ana, ext="png").json()["object_key"]  # no PUT
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (400, NO_PICTURE)
    assert avatar_in_db(ana.id) is None


@pytest.mark.parametrize(
    ("ext", "data"),
    [
        ("png", b"<html><script>alert(1)</script></html>"),
        ("png", made_up_picture("jpg")),  # a JPEG called .png
        ("jpg", made_up_picture("png")),  # a PNG called .jpg
        ("webp", b"RIFF\x24\x00\x00\x00AVI LIST" + bytes(100)),  # RIFF, but a video
        ("webp", b"\x00\x00\x00\x18ftypisom" + bytes(100)),  # an MP4
        ("png", b"\x89PNG"),  # too short to be a picture
        ("jpg", b""),  # empty
    ],
)
def test_confirm_refuses_a_file_whose_bytes_are_not_that_picture_type(client, ana, ext, data):
    object_key = upload(client, ana, ext=ext, data=data)
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (
        415,
        error(415, f"The uploaded file is not a {ext} picture"),
    )
    assert avatar_in_db(ana.id) is None


@pytest.mark.parametrize("content_type", ["text/html", "image/jpeg", None])
def test_confirm_refuses_a_picture_uploaded_with_another_content_type(client, ana, content_type):
    # MinIO would send this Content-Type to everyone who downloads the file: text/html would
    # make a browser run it as a page of our site. No header at all is stored as
    # application/octet-stream.
    object_key = upload(client, ana, ext="png", content_type=content_type)
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (
        415,
        error(415, "Upload the picture with the header Content-Type: image/png"),
    )
    assert avatar_in_db(ana.id) is None


def test_confirm_refuses_a_picture_over_5_mib(client, ana):
    object_key = upload(client, ana, data=made_up_picture("png", MAX_PICTURE_BYTES + 1))
    response = confirm(client, ana, object_key)
    assert (response.status_code, response.json()) == (
        413,
        error(413, "The picture is larger than 5 MiB"),
    )
    assert avatar_in_db(ana.id) is None


def test_a_picture_of_exactly_5_mib_is_accepted(client, ana):
    object_key = upload(client, ana, data=made_up_picture("png", MAX_PICTURE_BYTES))
    assert confirm(client, ana, object_key).status_code == 204


@pytest.mark.parametrize("body", [{}, {"object_key": "x" * 501}, {"object_key": None}])
def test_confirm_needs_an_object_key_of_at_most_500_characters(client, ana, body):
    response = client.post("/api/media/avatar/confirm", json=body, headers=ana.headers)
    assert response.status_code == 422


# --- A new picture replaces the old one ----------------------------------------------------


def test_a_new_avatar_deletes_the_old_file(client, ana, ben):
    bens_key = upload(client, ben)
    confirm(client, ben, bens_key)
    first = upload(client, ana, ext="jpg")
    assert confirm(client, ana, first).status_code == 204
    first_url = my_avatar_url(client, ana)
    second = upload(client, ana, ext="webp")
    assert confirm(client, ana, second).status_code == 204
    assert avatar_in_db(ana.id) == second
    assert not is_stored(first) and is_stored(second)
    # The old public link no longer gives the picture.
    assert httpx2.get(first_url).status_code == 404
    # Nobody else's file is touched.
    assert is_stored(bens_key)


def test_confirming_my_current_avatar_again_keeps_its_file(client, ana):
    object_key = upload(client, ana)
    assert confirm(client, ana, object_key).status_code == 204
    assert confirm(client, ana, object_key).status_code == 204
    assert avatar_in_db(ana.id) == object_key and is_stored(object_key)


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


def test_if_the_old_file_cannot_be_deleted_the_new_avatar_is_still_saved_and_logged(
    app, client, ana
):
    first = upload(client, ana)
    confirm(client, ana, first)
    second = upload(client, ana)

    def remove_fails(key: str) -> None:
        raise ConnectionError("MinIO is down")

    # Only the delete fails, on purpose: the checks before it still use the real MinIO.
    app.state.storage.remove = remove_fails
    with captured_logs() as logs:
        response = confirm(client, ana, second)
    assert response.status_code == 204
    assert avatar_in_db(ana.id) == second
    [line] = [line for line in logs if line["event"] == "file not removed from storage"]
    assert (line["level"], line["object_key"]) == ("error", first)


# --- Company logos -------------------------------------------------------------------------


def test_an_employer_uploads_and_confirms_a_logo_that_anyone_can_download(client, ana):
    company_id = make_company(ana)
    data = made_up_picture("webp")
    answer = ask_upload_url(client, ana, "company-logo", ext="webp").json()
    assert re.fullmatch(rf"logos/{company_id}/{UUID}\.webp", answer["object_key"])
    assert put_file(answer["put_url"], data, "image/webp") == 200
    response = confirm(client, ana, answer["object_key"], "company-logo")
    assert (response.status_code, response.content) == (204, b"")
    assert logo_in_db(company_id) == answer["object_key"]
    assert sql("SELECT updated_by_id FROM companies") == [(ana.id,)]
    # What CompanyOut's logo_url will be (BE-21), downloaded with no login.
    logo_url = pictures_app().state.storage.logo_url(answer["object_key"])
    assert logo_url == f"{EXTERNAL}/{TEST_BUCKET}/{answer['object_key']}"
    download = httpx2.get(logo_url)
    assert (download.status_code, download.content) == (200, data)


@pytest.mark.parametrize("company", [None, "deleted"])
@pytest.mark.parametrize("step", ["upload-url", "confirm"])
def test_logo_routes_are_for_employers_only(client, ana, company, step):
    if company:
        make_company(ana, status=company)  # a deleted company counts as none
    if step == "upload-url":
        response = ask_upload_url(client, ana, "company-logo", ext="png")
    else:
        response = confirm(client, ana, f"logos/1/{uuid4()}.png", "company-logo")
    assert (response.status_code, response.json()) == (404, NO_COMPANY)


def test_an_employer_cannot_use_another_companys_logo_or_an_avatar(client, ana, ben):
    make_company(ana)
    bens_company = make_company(ben)
    bens_logo = upload(client, ben, "company-logo")
    assert confirm(client, ben, bens_logo, "company-logo").status_code == 204
    anas_avatar = upload(client, ana)
    for object_key in (bens_logo, anas_avatar):
        response = confirm(client, ana, object_key, "company-logo")
        assert (response.status_code, response.json()) == (400, NOT_YOUR_KEY)
    assert logo_in_db(bens_company) == bens_logo and is_stored(bens_logo)


def test_the_logo_is_checked_like_an_avatar(client, ana):
    make_company(ana)
    response = ask_upload_url(client, ana, "company-logo", ext="gif")
    assert (response.status_code, response.json()) == (415, ONLY_PICTURES)
    object_key = upload(client, ana, "company-logo", data=b"GIF89a" + bytes(100))
    response = confirm(client, ana, object_key, "company-logo")
    assert response.json() == error(415, "The uploaded file is not a png picture")
    too_big = made_up_picture("png", MAX_PICTURE_BYTES + 1)
    object_key = upload(client, ana, "company-logo", data=too_big)
    assert confirm(client, ana, object_key, "company-logo").status_code == 413


def test_a_new_logo_deletes_the_old_file(client, ana):
    company_id = make_company(ana)
    first = upload(client, ana, "company-logo")
    confirm(client, ana, first, "company-logo")
    second = upload(client, ana, "company-logo", ext="jpg")
    assert confirm(client, ana, second, "company-logo").status_code == 204
    assert logo_in_db(company_id) == second
    assert not is_stored(first) and is_stored(second)


# --- Deleting the account ------------------------------------------------------------------


def test_deleting_my_account_deletes_my_avatar_file_at_once(client, ana, ben):
    bens_key = upload(client, ben)
    confirm(client, ben, bens_key)
    object_key = upload(client, ana)
    confirm(client, ana, object_key)
    avatar_url = my_avatar_url(client, ana)
    assert client.delete("/api/users/me", headers=ana.headers).status_code == 204
    assert not is_stored(object_key)
    assert httpx2.get(avatar_url).status_code == 404
    assert avatar_in_db(ana.id) is None
    # Ben's account and picture are untouched.
    assert avatar_in_db(ben.id) == bens_key and is_stored(bens_key)


def test_deleting_an_employers_account_deletes_the_company_logo_too(client, ana):
    company_id = make_company(ana)
    logo = upload(client, ana, "company-logo")
    confirm(client, ana, logo, "company-logo")
    assert client.delete("/api/users/me", headers=ana.headers).status_code == 204
    assert not is_stored(logo)
    assert logo_in_db(company_id) is None


def test_deleting_an_account_with_no_pictures_touches_no_file(client, ana, ben):
    bens_key = upload(client, ben)
    confirm(client, ben, bens_key)
    assert client.delete("/api/users/me", headers=ana.headers).status_code == 204
    assert sql("SELECT status FROM users WHERE id = :id", id=ana.id) == [("deleted",)]
    assert is_stored(bens_key)


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
