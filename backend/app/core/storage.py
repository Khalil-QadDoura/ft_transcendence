"""File storage: the MinIO bucket where the videos, avatars and logos are kept. Files never pass
through the API: the browser sends them straight to MinIO with a signed link, and the API checks
them there."""

import io
from datetime import timedelta
from urllib.parse import urlparse

import urllib3
from fastapi import Request
from minio import Minio
from minio.datatypes import Object
from minio.error import S3Error

from app.core.config import Settings

# How long the API waits for MinIO before giving up, in seconds.
CONNECT_TIMEOUT_SEC = 2
READ_TIMEOUT_SEC = 10


class Storage:
    """The bucket of one app, reached in two ways (INF-04)."""

    def __init__(self, settings: Settings):
        self.bucket = settings.minio_bucket
        keys = {
            "access_key": settings.minio_access_key,
            "secret_key": settings.minio_secret_key,
            "region": settings.minio_region,
        }
        # 1. "internal": what the server does itself (look at a file, read its first bytes).
        # It talks to minio:9000 inside the Docker network, over plain HTTP. Short timeouts and
        # no retries, so a request never hangs while MinIO is down.
        connection = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=CONNECT_TIMEOUT_SEC, read=READ_TIMEOUT_SEC),
            retries=False,
        )
        self.internal = Minio(settings.minio_endpoint, secure=False, http_client=connection, **keys)
        # 2. "external": only signs links, for the address the browser uses
        # (https://localhost/files/<key>). It never connects anywhere: with the region given,
        # signing is only a calculation with the secret key.
        public = urlparse(settings.minio_external_endpoint)
        self.external = Minio(public.netloc, secure=public.scheme == "https", **keys)
        # 3. Avatars and logos need no signed link at all: anyone may download the files under
        # avatars/ and logos/ (the bucket's anonymous policy, INF-04), at the same address the
        # signed links use, e.g. https://localhost/files/avatars/12/<uuid>.png. Only the
        # server writes there (put), after checking the picture.
        self.public_base = f"{public.scheme}://{public.netloc}/{self.bucket}"
        self.default_avatar_url = settings.default_avatar_url

    def public_url(self, key: str) -> str:
        """The plain address of a file under avatars/ or logos/: no signature, never expires."""
        return f"{self.public_base}/{key}"

    def avatar_url(self, key: str | None) -> str:
        """What the frontend shows for a user: their picture, or the default one if they have
        none. For UserOut now, and later for the public profile and the friends list."""
        return self.public_url(key) if key else self.default_avatar_url

    def logo_url(self, key: str | None) -> str | None:
        """A company's logo, or None if it has none. For CompanyOut (BE-21)."""
        return self.public_url(key) if key else None

    def upload_url(self, key: str, expires: timedelta) -> str:
        """A link that lets whoever has it PUT one file at this key, until it expires."""
        return self.external.presigned_put_object(self.bucket, key, expires)

    def download_url(self, key: str, expires: timedelta) -> str:
        """A link that lets whoever has it GET the file at this key, until it expires."""
        return self.external.presigned_get_object(self.bucket, key, expires)

    def stat(self, key: str) -> Object | None:
        """What MinIO knows about the stored file (stat_object): its real size and the
        Content-Type it was uploaded with. None if there is no file at this key."""
        try:
            return self.internal.stat_object(self.bucket, key)
        except S3Error as error:
            if error.code == "NoSuchKey":
                return None
            raise

    def size(self, key: str) -> int | None:
        """The real size of the stored file in bytes, or None if there is none."""
        stored = self.stat(key)
        return None if stored is None else stored.size

    def remove(self, key: str) -> None:
        """Delete the file at this key. A key with no file is not an error."""
        self.internal.remove_object(self.bucket, key)

    def read(self, key: str, max_bytes: int) -> bytes | None:
        """The stored file, but never more than max_bytes of it: a bigger file is cut there.
        None if there is no file at this key."""
        try:
            response = self.internal.get_object(self.bucket, key)
        except S3Error as error:
            if error.code == "NoSuchKey":
                return None
            raise
        try:
            return response.read(max_bytes)
        finally:
            response.close()  # also drops the rest of a file that was cut
            response.release_conn()

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Write a file ourselves, with the Content-Type we choose."""
        self.internal.put_object(
            self.bucket, key, io.BytesIO(data), len(data), content_type=content_type
        )

    def first_bytes(self, key: str, count: int) -> bytes:
        """The first bytes of the stored file, without downloading the rest."""
        response = self.internal.get_object(self.bucket, key, offset=0, length=count)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


def get_storage(request: Request) -> Storage:
    """FastAPI dependency: this app's storage, made once in create_app()."""
    return request.app.state.storage
