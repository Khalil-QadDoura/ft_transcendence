#!/usr/bin/env bash
# Smoke test of file storage (INF-04), from the host, over HTTPS through the proxy:
# - a presigned PUT and GET at https://<host>/files work; a tampered signature does not;
# - the bucket policy: anonymous download under avatars/ only, no anonymous list or upload;
# - downloads carry Content-Security-Policy: sandbox and X-Content-Type-Options: nosniff,
#   also for an uploaded HTML page, so it cannot run as a page of our origin;
# - then prints a snippet for the Chrome console with fresh presigned URLs.
# Needs the stack up (`make`). Run it with `make files-check`. Exits 1 when a check fails.
# Needs network access once per run (pip installs the MinIO SDK). Works with bash 3.2 (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
CA="$ROOT/infra/proxy/certs/server.crt"
# Same Python as the api image, plus the MinIO SDK the backend is expected to use.
PYTHON_IMAGE=python:3.11-slim@sha256:6d85378d88a19cd4d76079817532d62232be95757cb45945a99fec8e8084b9c2
MINIO_SDK=minio==7.2.20
PUBLIC_KEY=avatars/inf04-test.txt
PRIVATE_KEY=videos/inf04-test.txt
BROWSER_KEY=videos/inf04-browser.txt
HTML_KEY=avatars/inf04-test.html

api="$(docker compose ps -q api)"
minio="$(docker compose ps -q minio)"
if [ -z "$api" ] || [ -z "$minio" ]; then
    echo "files-check: the stack is not running; start it with make" >&2
    exit 1
fi

# The storage settings exactly as compose gives them to the API. Exported, and passed to
# the helper container by name only, so no value appears on a command line or in output.
while IFS= read -r line; do
    # shellcheck disable=SC2163 # $line is NAME=value, so this exports NAME
    case "$line" in MINIO_*=*) export "$line" ;; esac
done < <(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$api")
network="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}' "$minio")"
files="$MINIO_EXTERNAL_ENDPOINT/$MINIO_BUCKET"

work="$(mktemp -d)"
helper=""
cleanup() {
    if [ -n "$helper" ]; then
        docker exec "$helper" python -I /smoke-test.py remove "$PUBLIC_KEY" "$PRIVATE_KEY" "$HTML_KEY" \
            >/dev/null 2>&1 || true
        docker rm -f "$helper" >/dev/null 2>&1 || true
    fi
    rm -rf "$work"
}
trap cleanup EXIT

echo "files-check: $files (region $MINIO_REGION), CA $CA"
helper="$(docker run -d --rm --network "$network" \
    -e MINIO_ENDPOINT -e MINIO_EXTERNAL_ENDPOINT -e MINIO_BUCKET -e MINIO_REGION \
    -e MINIO_ACCESS_KEY -e MINIO_SECRET_KEY \
    -v "$ROOT/infra/minio/smoke-test.py:/smoke-test.py:ro" \
    "$PYTHON_IMAGE" sleep 300)"
docker exec "$helper" pip install -q --disable-pip-version-check --root-user-action=ignore "$MINIO_SDK"
py() { docker exec "$helper" python -I /smoke-test.py "$@"; }

failed=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failed=1; }
# check NAME EXPECTED CURL_ARGS...: one request; the response body lands in $work/body,
# its headers in $work/headers.
check() {
    local name="$1" expected="$2" status
    shift 2
    status="$(curl -sS --cacert "$CA" -o "$work/body" -D "$work/headers" -w '%{http_code}' "$@")" \
        || status="curl error"
    if [ "$status" = "$expected" ]; then
        pass "$name: $status"
    else
        fail "$name: $status, expected $expected"
    fi
}
# has_header NAME 'Header: value': the last response carries this header exactly once.
has_header() {
    local count
    count="$(tr -d '\r' < "$work/headers" | grep -ci "^$2\$" || true)"
    if [ "$count" = 1 ]; then
        pass "$1: $2"
    else
        fail "$1: $2 sent $count times, expected once"
    fi
}
# The proxy adds both to every /files response (infra/proxy, location /files/).
has_security_headers() {
    has_header "$1" 'Content-Security-Policy: sandbox'
    has_header "$1" 'X-Content-Type-Options: nosniff'
}

py put "$PUBLIC_KEY"
urls="$(py urls "$PRIVATE_KEY")"
put_url="${urls%%$'\n'*}"
get_url="${urls#*$'\n'}"
printf 'inf04 smoke test %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$work/upload.txt"

echo "Presigned URLs:"
check "PUT $PRIVATE_KEY" 200 -X PUT --upload-file "$work/upload.txt" "$put_url"
check "GET $PRIVATE_KEY" 200 "$get_url"
has_security_headers "GET $PRIVATE_KEY"
if cmp -s "$work/upload.txt" "$work/body"; then
    pass "downloaded content matches the upload"
else
    fail "downloaded content differs from the upload"
fi
sig="${get_url##*X-Amz-Signature=}"
sig="${sig%%&*}"
case "$sig" in 0*) bad="1${sig#?}" ;; *) bad="0${sig#?}" ;; esac
check "GET with a tampered signature" 403 "${get_url/$sig/$bad}"
if grep -q SignatureDoesNotMatch "$work/body"; then
    pass "error code SignatureDoesNotMatch"
else
    fail "error code SignatureDoesNotMatch missing"
fi

echo "Anonymous requests (bucket policy):"
check "GET $PUBLIC_KEY (public prefix)" 200 "$files/$PUBLIC_KEY"
has_security_headers "GET $PUBLIC_KEY"
check "GET $PRIVATE_KEY (private)" 403 "$files/$PRIVATE_KEY"
check "list the bucket" 403 "$files/"
check "list the avatars/ prefix" 403 "$files/?prefix=avatars/"
check "PUT avatars/inf04-anonymous.txt" 403 -X PUT --data-binary x "$files/avatars/inf04-anonymous.txt"

# What a user can do with their own upload link: the type is the one the uploader sends.
echo "Uploaded HTML page (served, but sandboxed):"
urls="$(py urls "$HTML_KEY")"
put_url="${urls%%$'\n'*}"
printf '<!doctype html><script>alert(document.domain)</script>\n' > "$work/page.html"
check "PUT $HTML_KEY as text/html" 200 -X PUT -H 'Content-Type: text/html' \
    --upload-file "$work/page.html" "$put_url"
check "GET $HTML_KEY (public prefix)" 200 "$files/$HTML_KEY"
has_header "GET $HTML_KEY" 'Content-Type: text/html'
has_security_headers "GET $HTML_KEY"

if [ "$failed" -ne 0 ]; then
    echo "files-check: FAILED"
    exit 1
fi
echo "files-check: all checks passed"

urls="$(py urls "$BROWSER_KEY")"
put_url="${urls%%$'\n'*}"
get_url="${urls#*$'\n'}"
cat <<EOF

Browser check: open $MINIO_EXTERNAL_ENDPOINT/ in Chrome and paste this into the DevTools
console within 5 minutes. Expected: "PUT 200", then "GET 200 hello", nothing else.

(async () => { const put = await fetch('$put_url', {method: 'PUT', body: 'hello'}); console.log('PUT', put.status); const get = await fetch('$get_url'); console.log('GET', get.status, await get.text()); })();
EOF
