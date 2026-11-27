#!/usr/bin/env bash
# Keeps the public address in .env in step with the HTTPS host port (QA-01). `make` runs it
# between env and up.
# 1. HTTPS_PORT or HTTP_PORT set in the shell (`HTTPS_PORT=8443 make`) and different from
#    .env: the new value is written into .env, so the next plain `make` keeps it.
# 2. FRONTEND_BASE_URL (email links, the 42 redirect URI, Grafana's root URL) and
#    MINIO_EXTERNAL_ENDPOINT (presigned file URLs) carry the port when HTTPS_PORT is not 443:
#    https://<host> becomes https://<host>:<HTTPS_PORT>; a port left from an earlier change
#    is replaced, and with 443 it is removed again. Any other value (another scheme, a path,
#    a trailing slash) is left as it is, with a warning.
# Prints key names, ports and the public address only. .env stays readable by its owner
# only. Works with bash 3.2 and BSD tools (macOS): no sed -i.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
URL_KEYS="FRONTEND_BASE_URL MINIO_EXTERNAL_ENDPOINT"

[ -f "$ENV_FILE" ] || { echo "ports: .env not found; run make env first" >&2; exit 1; }

umask 077
TMP=""
trap 'if [ -n "$TMP" ]; then rm -f "$TMP"; fi' EXIT

# env_get KEY: the value compose reads for KEY in .env (the last line wins; `export ` and
# indentation allowed; surrounding quotes removed). Empty when KEY is missing.
env_get() {
    awk -v k="$1" '
        { line = $0; sub(/\r$/, "", line); sub(/^[ \t]+/, "", line); sub(/^export[ \t]+/, "", line) }
        index(line, k "=") == 1 { v = substr(line, length(k) + 2); sub(/[ \t]+$/, "", v) }
        END {
            if (v ~ /^".*"$/ || v ~ /^\047.*\047$/) v = substr(v, 2, length(v) - 2)
            print v
        }' "$ENV_FILE"
}

# env_set KEY VALUE: every line of KEY becomes KEY=VALUE (appended when missing). Written to
# a temporary file next to .env (mode 600), then moved over it.
env_set() {
    TMP="$(mktemp "$ROOT/.env.XXXXXX")"
    awk -v k="$1" -v v="$2" '
        { line = $0; sub(/^[ \t]+/, "", line); sub(/^export[ \t]+/, "", line) }
        index(line, k "=") == 1 { print k "=" v; done = 1; next }
        { print }
        END { if (!done) print k "=" v }' "$ENV_FILE" > "$TMP"
    mv "$TMP" "$ENV_FILE"
    TMP=""
}

valid_port() {
    case "$1" in
        "" | *[!0-9]*) return 1 ;;
    esac
    [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

# 1. Ports given in the shell.
for key in HTTPS_PORT HTTP_PORT; do
    given="$(printenv "$key" || true)"
    [ -n "$given" ] || continue
    if ! valid_port "$given"; then
        echo "ports: $key=$given in the environment is not a port number (1-65535)" >&2
        exit 1
    fi
    if [ "$given" != "$(env_get "$key")" ]; then
        env_set "$key" "$given"
        echo "ports: $key=$given (from the environment) written to .env"
    fi
done

# 2. The public URLs.
https_port="$(env_get HTTPS_PORT)"
https_port="${https_port:-443}"
if ! valid_port "$https_port"; then
    echo "ports: HTTPS_PORT in .env is not a port number (1-65535)" >&2
    exit 1
fi
if [ "$https_port" = 443 ]; then suffix=""; else suffix=":$https_port"; fi

changed=""
for key in $URL_KEYS; do
    value="$(env_get "$key")"
    # https://<host> or https://<host>:<port>, nothing after it.
    host="$(printf '%s\n' "$value" | sed -n -E 's#^https://([A-Za-z0-9.-]+)(:[0-9]+)?$#\1#p')"
    if [ -z "$host" ]; then
        echo "ports: WARNING: $key is not https://<host>[:<port>]; left as it is." \
            "With HTTPS_PORT=$https_port it should be https://<host>$suffix" >&2
        continue
    fi
    wanted="https://$host$suffix"
    [ "$value" != "$wanted" ] || continue
    # An explicit :443 is the same address as none.
    [ -n "$suffix" ] || [ "$value" != "https://$host:443" ] || continue
    env_set "$key" "$wanted"
    echo "ports: $key set to $wanted (HTTPS_PORT=$https_port)"
    changed=yes
done

if [ -z "$changed" ]; then
    echo "ports: HTTPS_PORT=$https_port; the public URLs in .env already match"
fi
