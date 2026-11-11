"""File storage: the MinIO bucket where the videos are kept. Files never pass through the API:
the browser sends them straight to MinIO with a signed link, and the API checks them there."""

from datetime import timedelta
from urllib.parse import urlparse

import urllib3
from fastapi import Request
from minio import Minio
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

    def upload_url(self, key: str, expires: timedelta) -> str:
        """A link that lets whoever has it PUT one file at this key, until it expires."""
        return self.external.presigned_put_object(self.bucket, key, expires)

    def download_url(self, key: str, expires: timedelta) -> str:
        """A link that lets whoever has it GET the file at this key, until it expires."""
        return self.external.presigned_get_object(self.bucket, key, expires)

    def size(self, key: str) -> int | None:
        """The real size of the stored file in bytes (stat_object), or None if there is none."""
        try:
            return self.internal.stat_object(self.bucket, key).size
        except S3Error as error:
            if error.code == "NoSuchKey":
                return None
            raise

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
