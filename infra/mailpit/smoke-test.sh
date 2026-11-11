#!/usr/bin/env bash
# Smoke test of sign-up email (INF-05), from the host, over HTTPS through the proxy only:
# - the API reads SMTP_HOST, SMTP_PORT, MAIL_FROM and FRONTEND_BASE_URL, and no Brevo key;
# - POST /api/auth/register with a fresh address puts a message into Mailpit at /mail;
# - its sender is MAIL_FROM, its link is FRONTEND_BASE_URL/verify-email?token=..., and that
#   link opens the frontend (index.html);
# - login is refused before the link is used; the verify endpoint accepts the token; login
#   then works.
# Deletes its message from Mailpit at the end; the test user stays in the database (one per
# run, inf05-check-<timestamp>@example.com). Sign-up allows 5 requests per minute per IP.
# Needs the stack up (`make`). Run it with `make mail-check`. Exits 1 when a check fails.
# Works with bash 3.2 (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
CA="$ROOT/infra/proxy/certs/server.crt"
# example.com is reserved for examples (RFC 2606). The API rejects example.test: the email
# validator refuses special-use names such as .test and .local as recipients.
EMAIL="inf05-check-$(date -u +%Y%m%d%H%M%S)@example.com"
# How long to wait for the email: the API sends it after answering the sign-up.
WAIT_SEC=15

for service in proxy api mailpit; do
    if [ -z "$(docker compose ps -q "$service")" ]; then
        echo "mail-check: the stack is not running; start it with make" >&2
        exit 1
    fi
done

https_port="$(docker compose port proxy 8443)"
https_port="${https_port##*:}"
if [ "$https_port" = 443 ]; then base=https://localhost; else base="https://localhost:$https_port"; fi
mail_api="$base/mail/api/v1"

work="$(mktemp -d)"
message_id=""
cleanup() {
    if [ -n "$message_id" ]; then
        curl -sS --cacert "$CA" -o /dev/null -X DELETE -H 'Content-Type: application/json' \
            --data "{\"IDs\":[\"$message_id\"]}" "$mail_api/messages" || true
    fi
    rm -rf "$work"
}
trap cleanup EXIT

failed=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failed=1; }
# req URL CURL_ARGS...: one request. Sets $status and $ctype; the body lands in $work/body.
req() {
    local url="$1" out
    shift
    out="$(curl -sS --cacert "$CA" -o "$work/body" -w '%{http_code}|%{content_type}' "$@" "$url" 2>/dev/null)" || true
    IFS='|' read -r status ctype <<EOF
${out:-000|}
EOF
}
# json_string KEY: the first "KEY":"value" in $work/body (enough for these flat answers).
json_string() {
    grep -o "\"$1\":\"[^\"]*\"" "$work/body" | head -n 1 | sed 's/^[^:]*:"//; s/"$//' || true
}

echo "mail-check: $base, inbox $base/mail/, test user $EMAIL"

echo "Settings (as the API reads them):"
# Through the app's own Settings class, so a renamed variable shows up as a default value.
settings="$(docker compose exec -T api python -c 'from app.core.config import get_settings
s = get_settings()
print(s.smtp_host, s.smtp_port, s.mail_from, s.frontend_base_url, "set" if s.brevo_api_key else "unset")')"
read -r smtp_host smtp_port mail_from frontend_base_url brevo <<EOF
$settings
EOF
if [ "$smtp_host:$smtp_port" = mailpit:1025 ]; then
    pass "SMTP_HOST:SMTP_PORT = $smtp_host:$smtp_port"
else
    fail "SMTP_HOST:SMTP_PORT = $smtp_host:$smtp_port, expected mailpit:1025"
fi
pass "MAIL_FROM = $mail_from"
if [ "${frontend_base_url%/}" = "$base" ]; then
    pass "FRONTEND_BASE_URL = $frontend_base_url"
else
    fail "FRONTEND_BASE_URL = $frontend_base_url, expected $base (the port goes in .env too)"
fi
if [ "$brevo" = unset ]; then
    pass "BREVO_API_KEY not set: mail goes over SMTP to Mailpit"
else
    fail "BREVO_API_KEY is set: mail would leave through Brevo"
fi

echo "Sign-up through $base/api:"
req "$mail_api/info"
if [ "$status" = 200 ]; then
    pass "GET /mail/api/v1/info: 200 (Mailpit $(json_string Version))"
else
    fail "GET /mail/api/v1/info: $status, expected 200"
fi
password="Inf05-$(openssl rand -hex 12)"
printf '{"email":"%s","password":"%s"}' "$EMAIL" "$password" > "$work/credentials.json"
req "$base/api/auth/register" -H 'Content-Type: application/json' --data "@$work/credentials.json"
if [ "$status" = 202 ]; then
    pass "POST /api/auth/register: 202"
else
    fail "POST /api/auth/register: $status $(head -c 200 "$work/body"), expected 202"
fi
req "$base/api/auth/login" -H 'Content-Type: application/json' --data "@$work/credentials.json"
if [ "$status" = 403 ]; then
    pass "POST /api/auth/login before verifying: 403"
else
    fail "POST /api/auth/login before verifying: $status, expected 403"
fi

echo "Email in Mailpit:"
count=0
for _ in $(seq "$WAIT_SEC"); do
    req "$mail_api/search" --get --data-urlencode "query=to:$EMAIL"
    count="$(grep -o '"messages_count":[0-9]*' "$work/body" | head -n 1 | cut -d: -f2 || true)"
    if [ "${count:-0}" -gt 0 ]; then break; fi
    sleep 1
done
if [ "${count:-0}" = 1 ]; then
    message_id="$(json_string ID)"
    pass "message to $EMAIL arrived"
else
    fail "messages to $EMAIL: ${count:-0} after ${WAIT_SEC}s, expected 1 (make logs s=api)"
fi

link=""
if [ -n "$message_id" ]; then
    req "$mail_api/message/$message_id"
    from="$(grep -o '"From":{[^}]*}' "$work/body" | grep -o '"Address":"[^"]*"' | sed 's/.*:"//; s/"$//' || true)"
    if [ "$from" = "$mail_from" ]; then
        pass "From: $from (MAIL_FROM)"
    else
        fail "From: ${from:-none}, expected $mail_from"
    fi
    pass "Subject: $(json_string Subject)"
    link="$(grep -o 'https://[^"\\ ]*/verify-email?token=[A-Za-z0-9._-]*' "$work/body" | head -n 1 || true)"
    case "$link" in
        "${frontend_base_url%/}/verify-email?token="?*) pass "link: ${link%%\?*}?token=… (FRONTEND_BASE_URL + /verify-email)" ;;
        *) fail "link: ${link:-none}, expected ${frontend_base_url%/}/verify-email?token=…" ;;
    esac
fi

if [ -n "$link" ]; then
    echo "Link and verification:"
    req "$link"
    if [ "$status" = 200 ] && [ "${ctype%%;*}" = text/html ] && grep -q '<div id="root">' "$work/body"; then
        pass "GET the link: 200 index.html (the frontend's /verify-email route, FE-04)"
    else
        fail "GET the link: $status $ctype, expected 200 text/html with index.html"
    fi
    token="${link#*token=}"
    req "$base/api/auth/verify" --get --data-urlencode "token=$token"
    if [ "$status" = 200 ] && grep -q '"verified":true' "$work/body"; then
        pass "GET /api/auth/verify?token=…: 200 verified"
    else
        fail "GET /api/auth/verify?token=…: $status $(head -c 200 "$work/body"), expected 200 verified"
    fi
    req "$base/api/auth/login" -H 'Content-Type: application/json' --data "@$work/credentials.json"
    if [ "$status" = 200 ] && grep -q '"access_token":"' "$work/body"; then
        pass "POST /api/auth/login after verifying: 200 with tokens"
    else
        fail "POST /api/auth/login after verifying: $status, expected 200 with tokens"
    fi
fi

if [ -n "$message_id" ]; then
    req "$mail_api/messages" -X DELETE -H 'Content-Type: application/json' \
        --data "{\"IDs\":[\"$message_id\"]}"
    if [ "$status" = 200 ]; then
        pass "message deleted from Mailpit"
        message_id=""
    else
        fail "DELETE the message: $status, expected 200"
    fi
fi

if [ "$failed" -ne 0 ]; then
    echo "mail-check: FAILED"
    exit 1
fi
echo "mail-check: all checks passed"
