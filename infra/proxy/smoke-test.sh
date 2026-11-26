#!/usr/bin/env bash
# Smoke test of the single HTTPS origin (INF-03), from the host, through the proxy:
# - / serves the frontend with the SPA fallback; a missing asset is a 404, not index.html;
# - /api/health answers; /ws completes a WebSocket handshake with the API (101, or FAIL);
# - http:// redirects to https:// with path, query and host port kept; nginx's own
#   trailing-slash redirects (/mail -> /mail/) keep the host port too;
# - /_internal and /metrics, also under /api, are 404 from outside, even with the key,
#   while the internal route works inside the Docker network;
# - only the proxy publishes host ports.
# Needs the stack up (`make`). Run it with `make https-check`. Exits 1 when a check fails.
# WS_PATH (default /ws) moves the WebSocket check to another path, to see it fail:
# `WS_PATH=/ws-missing make https-check`. Works with bash 3.2 (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
CA="$ROOT/infra/proxy/certs/server.crt"
# RFC 6455: the server proves it speaks WebSocket by hashing the client key with this GUID.
WS_GUID=258EAFA5-E914-47DA-95CA-C5AB0DC85B11
ws_path="${WS_PATH:-/ws}"
case "$ws_path" in
    /*) ;;
    *) echo "https-check: WS_PATH must start with /" >&2; exit 1 ;;
esac

for service in proxy frontend api; do
    if [ -z "$(docker compose ps -q "$service")" ]; then
        echo "https-check: the stack is not running; start it with make" >&2
        exit 1
    fi
done

# The host ports as compose published them (HTTPS_PORT / HTTP_PORT in .env).
https_port="$(docker compose port proxy 8443)"
https_port="${https_port##*:}"
http_port="$(docker compose port proxy 8080)"
http_port="${http_port##*:}"
if [ "$https_port" = 443 ]; then base=https://localhost; else base="https://localhost:$https_port"; fi
if [ "$http_port" = 80 ]; then http_base=http://localhost; else http_base="http://localhost:$http_port"; fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

failed=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failed=1; }
skip() { printf '  SKIP  %s\n' "$1"; }
# req URL CURL_ARGS...: one request. Sets $status, $location (absolute, resolved by curl)
# and $ctype; the body lands in $work/body, the response headers in $work/headers.
req() {
    local url="$1" out
    shift
    out="$(curl -sS --cacert "$CA" -o "$work/body" -D "$work/headers" \
        -w '%{http_code}|%{redirect_url}|%{content_type}' "$@" "$url" 2>/dev/null)" || true
    IFS='|' read -r status location ctype <<EOF
${out:-000||}
EOF
}
# spa NAME PATH: 200 text/html with the frontend's index.html.
spa() {
    req "$base$2"
    if [ "$status" = 200 ] && [ "${ctype%%;*}" = text/html ] && grep -q '<div id="root">' "$work/body"; then
        pass "$1: 200 index.html"
    else
        fail "$1: $status $ctype, expected 200 text/html with index.html"
    fi
}
# blocked NAME URL CURL_ARGS...: 404 from the proxy itself (an HTML page), not the API's
# JSON 404 and not the frontend's index.html.
blocked() {
    local name="$1"
    shift
    req "$@"
    if [ "$status" = 404 ] && [ "${ctype%%;*}" = text/html ] && ! grep -q '<div id="root">' "$work/body"; then
        pass "$name: 404 from the proxy"
    else
        fail "$name: $status $ctype, expected 404 from the proxy"
    fi
}
# redirect NAME URL EXPECTED_LOCATION: 301 to exactly that URL.
redirect() {
    req "$2"
    if [ "$status" = 301 ] && [ "$location" = "$3" ]; then
        pass "$1: 301 $location"
    else
        fail "$1: $status ${location:-no Location}, expected 301 $3"
    fi
}

echo "https-check: $base (HTTP $http_base), CA $CA"

echo "Frontend (/ -> frontend:80):"
spa "GET /" /
spa "deep link /friends" /friends
spa "deep link /login" /login
spa "deep link /game/rules" /game/rules
req "$base/assets/inf03-missing.js"
if [ "$status" = 404 ]; then
    pass "missing /assets/inf03-missing.js: 404"
else
    fail "missing /assets/inf03-missing.js: $status $ctype, expected 404 (not index.html)"
fi
req "$base/"
asset="$(grep -o '/assets/[^"]*\.js' "$work/body" | head -n 1 || true)"
if [ -n "$asset" ]; then
    req "$base$asset"
    case "$status $ctype" in
        "200 application/javascript"* | "200 text/javascript"*) pass "GET $asset: 200 $ctype" ;;
        *) fail "GET $asset: $status $ctype, expected 200 JavaScript" ;;
    esac
else
    fail "index.html names no /assets/*.js"
fi

echo "API (/api/* -> api:8000, prefix kept):"
req "$base/api/health"
if [ "$status" = 200 ] && grep -q '"ok"' "$work/body"; then
    pass "GET /api/health: 200 $(cat "$work/body")"
else
    fail "GET /api/health: $status, expected 200 {\"status\":\"ok\"}"
fi

echo "WebSocket (/ws -> api:8000, HTTP/1.1 upgrade):"
# A real handshake over TLS. HTTP/1.1 only: over HTTP/2 curl drops Upgrade and Connection.
# No ticket on purpose: BE-06 accepts the socket first (101), then closes it with 1008.
# Only 101 passes: 403 (route missing or rejected), 404, 426, 502, a timeout (000) or the
# frontend's index.html all fail. After the 101 curl keeps reading the socket, so
# --max-time is what ends the request; it also bounds a proxy or API that never answers.
ws_key="$(openssl rand -base64 16)"
ws_accept="$(printf '%s' "$ws_key$WS_GUID" | openssl dgst -sha1 -binary | openssl base64)"
req "$base$ws_path" --http1.1 --max-time 3 -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Version: 13' -H "Sec-WebSocket-Key: $ws_key"
if [ "$status" = 101 ]; then
    got="$(tr -d '\r' < "$work/headers" | sed -n 's/^[Ss]ec-[Ww]eb[Ss]ocket-[Aa]ccept: *//p')"
    # The first frame, if any: bytes 3-4 of a close frame are its code (03f0 = 1008).
    close="$(od -An -tx1 -j2 -N2 "$work/body" | tr -d ' \n')"
    then_closed=""
    [ "$close" = 03f0 ] && then_closed=", then close 1008 (no ticket)"
    if [ "$got" = "$ws_accept" ]; then
        pass "wss://...$ws_path: 101 Switching Protocols, Sec-WebSocket-Accept matches$then_closed"
    else
        fail "wss://...$ws_path: 101 without the expected Sec-WebSocket-Accept"
    fi
else
    fail "wss://...$ws_path: $status ${ctype:-no Content-Type}, expected 101 Switching Protocols"
fi

echo "Redirects:"
redirect "http:// keeps path and query" "$http_base/inf03/x?y=1" "$base/inf03/x?y=1"
for path in /mail /files /api /grafana /assets; do
    redirect "$path keeps the host port" "$base$path" "$base$path/"
done
req "$base/mail/"
if [ "$status" = 200 ] && [ "${ctype%%;*}" = text/html ]; then
    pass "GET /mail/: 200 (Mailpit)"
else
    fail "GET /mail/: $status $ctype, expected 200 text/html"
fi

echo "Internal routes (404 from outside, even with the key):"
# The key goes to curl as a header file: never on a command line or in the output.
(umask 077 && docker compose exec -T api printenv INTERNAL_API_KEY \
    | sed 's/^/X-Internal-Key: /' > "$work/key-header") || true
blocked "GET /_internal/health/db with the key" "$base/_internal/health/db" -H "@$work/key-header"
blocked "GET /api/_internal/health/db with the key" "$base/api/_internal/health/db" -H "@$work/key-header"
blocked "GET /metrics" "$base/metrics"
blocked "GET /metrics/nginx (the image's)" "$base/metrics/nginx"
blocked "GET /api/metrics" "$base/api/metrics"
blocked "GET /api/../_internal/health/db" "$base/api/../_internal/health/db" -H "@$work/key-header" --path-as-is
blocked "GET /ws/../_internal/health/db" "$base/ws/../_internal/health/db" -H "@$work/key-header" --path-as-is
blocked "GET //_internal/health/db" "$base//_internal/health/db" -H "@$work/key-header" --path-as-is
blocked "GET /%5Finternal/health/db" "$base/%5Finternal/health/db" -H "@$work/key-header"
blocked "GET /_internal%2Fhealth/db" "$base/_internal%2Fhealth/db" -H "@$work/key-header"
if grep -q '^X-Internal-Key: .' "$work/key-header"; then
    # Inside the network the same route answers: the 404s above are the proxy's doing.
    inside="$(docker compose exec -T api python -c 'import os, urllib.request
r = urllib.request.Request("http://127.0.0.1:8000/_internal/health/db",
                           headers={"X-Internal-Key": os.environ["INTERNAL_API_KEY"]})
print(urllib.request.urlopen(r, timeout=5).status)' 2>&1)" || true
    if [ "$inside" = 200 ]; then
        pass "GET /_internal/health/db inside the network, with the key: 200"
    else
        fail "GET /_internal/health/db inside the network: $inside, expected 200"
    fi
else
    skip "inside the network: INTERNAL_API_KEY is empty, so /_internal is closed everywhere"
fi

echo "Host ports:"
# Every container of this compose project, whatever its profile: the name compose resolves
# (COMPOSE_PROJECT_NAME, else `name:` in docker-compose.yml), not a fixed one (QA-01).
project="$(docker compose config --no-interpolate 2>/dev/null | sed -n '1s/^name: //p')"
published="$(docker ps --filter "label=com.docker.compose.project=${project:?}" \
    --format '{{.Label "com.docker.compose.service"}} {{.Ports}}' | grep -e '->' | cut -d' ' -f1 | sort -u | tr '\n' ' ')"
if [ "$published" = "proxy " ]; then
    pass "only the proxy publishes host ports"
else
    fail "services with host ports: ${published:-none}, expected proxy only"
fi

if [ "$failed" -ne 0 ]; then
    echo "https-check: FAILED"
    exit 1
fi
echo "https-check: all checks passed"
