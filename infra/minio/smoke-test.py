"""Helper of smoke-test.sh: signs URLs the way the API will (BE-07, BE-08).

Runs in a throwaway Python container on the compose network, with the MINIO_* variables
of the api container. Two clients, as in the backend contract:
- internal (MINIO_ENDPOINT, plain HTTP) for server-side work: put and remove objects;
- external (MINIO_EXTERNAL_ENDPOINT + MINIO_REGION) only signs. With the region given the
  SDK makes no network call, which matters: in a container https://localhost is itself.

Usage:
  smoke-test.py put KEY        store a small text object
  smoke-test.py remove KEY...  delete objects (a missing one is not an error)
  smoke-test.py urls KEY       print a presigned PUT URL, then a presigned GET URL
"""

import io
import os
import sys
from datetime import timedelta
from urllib.parse import urlparse

from minio import Minio

# Same lifetimes as the API contract: 15 min to upload, 5 min to view.
PUT_EXPIRES = timedelta(minutes=15)
GET_EXPIRES = timedelta(minutes=5)


def client(url: str, region: str | None = None) -> Minio:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    return Minio(
        parsed.netloc,
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=parsed.scheme == "https",
        region=region,
    )


def main() -> None:
    bucket = os.environ["MINIO_BUCKET"]
    internal = client(os.environ["MINIO_ENDPOINT"])
    external = client(os.environ["MINIO_EXTERNAL_ENDPOINT"], os.environ["MINIO_REGION"])
    command, keys = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 2 else ("", [])

    if command == "put" and len(keys) == 1:
        data = b"inf04 smoke test\n"
        internal.put_object(bucket, keys[0], io.BytesIO(data), len(data), "text/plain")
    elif command == "remove":
        for key in keys:
            internal.remove_object(bucket, key)
    elif command == "urls" and len(keys) == 1:
        print(external.presigned_put_object(bucket, keys[0], PUT_EXPIRES))
        print(external.presigned_get_object(bucket, keys[0], GET_EXPIRES))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
