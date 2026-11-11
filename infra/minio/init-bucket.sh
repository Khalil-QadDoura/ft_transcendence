#!/usr/bin/env bash
# minio-init (INF-04): waits for MinIO, creates the bucket and sets its anonymous policy,
# then exits. Runs on every `make`; running it again changes nothing. Runs in the MinIO
# server image, which ships the mc client (and bash, but no sed or awk).
#
# The bucket is private. Anyone may download objects under PUBLIC_PREFIXES (no listing,
# no writes); everything else is reachable only through presigned URLs from the API.
set -euo pipefail

: "${MINIO_ROOT_USER:?}" "${MINIO_ROOT_PASSWORD:?}" "${MINIO_BUCKET:?}"

# Anonymous download, one prefix per word. Proposal for BE-08 (avatar_url, logo_url).
PUBLIC_PREFIXES="avatars logos"
# Seconds to wait for MinIO before giving up with a non-zero exit.
WAIT_SECONDS=60

# mc reads the alias from the environment: the credentials stay out of argv, config files
# and output. They must be URL-safe; init-env.sh generates hex.
export MC_HOST_wozu="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000"
target="wozu/$MINIO_BUCKET"

echo "minio-init: waiting up to ${WAIT_SECONDS}s for minio:9000"
if ! timeout "$WAIT_SECONDS" mc ready wozu >/dev/null; then
    echo "minio-init: MinIO did not become ready in ${WAIT_SECONDS}s" >&2
    exit 1
fi

# mc mb prints "created" even for an existing bucket, so the log says which case it was.
if mc stat "$target" >/dev/null 2>&1; then
    echo "minio-init: bucket $MINIO_BUCKET already exists"
else
    mc mb --ignore-existing "$target"
fi

resources=""
for prefix in $PUBLIC_PREFIXES; do
    resources="$resources${resources:+,}\"arn:aws:s3:::$MINIO_BUCKET/$prefix/*\""
done

if [ -z "$resources" ]; then
    mc anonymous set private "$target"
else
    policy="$(mktemp)"
    trap 'rm -f "$policy"' EXIT
    # s3:GetObject only: no s3:ListBucket, so nobody can list the bucket or a prefix.
    printf '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"AWS":["*"]},"Action":["s3:GetObject"],"Resource":[%s]}]}\n' \
        "$resources" > "$policy"
    mc anonymous set-json "$policy" "$target"
fi

echo "minio-init: anonymous policy of $MINIO_BUCKET:"
mc anonymous get-json "$target"
echo "minio-init: done"
