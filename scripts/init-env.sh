#!/usr/bin/env bash
# Creates .env from .env.example when .env is missing, filling each empty secret below
# with a random value. Never touches an existing .env, so running it again changes nothing.
# Prints the names of the generated values, never the values. Works with bash 3.2 (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
EXAMPLE="$ROOT/.env.example"
# Filled only where .env.example leaves the value empty.
SECRETS="JWT_SECRET INTERNAL_API_KEY POSTGRES_PASSWORD MINIO_ROOT_PASSWORD GRAFANA_ADMIN_PASSWORD"

remind_openai() {
    if grep -q '^OPENAI_API_KEY=$' "$ENV_FILE"; then
        echo "init-env: OPENAI_API_KEY is empty; add it to .env by hand for video moderation"
    fi
}

if [ -f "$ENV_FILE" ]; then
    echo "init-env: keeping existing .env"
    remind_openai
    exit 0
fi

command -v openssl >/dev/null || { echo "init-env: openssl is required" >&2; exit 1; }
[ -f "$EXAMPLE" ] || { echo "init-env: $EXAMPLE not found" >&2; exit 1; }

# The new file is readable by the owner only and appears under its final name only when complete.
umask 077
TMP="$(mktemp "$ROOT/.env.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

generated=""
while IFS= read -r line || [ -n "$line" ]; do
    name="${line%%=*}"
    case " $SECRETS " in
        *" $name "*)
            if [ "$line" = "$name=" ]; then
                # Hex: safe inside a database URL and in any shell or YAML context.
                printf '%s=%s\n' "$name" "$(openssl rand -hex 32)"
                generated="$generated $name"
                continue
            fi
            ;;
    esac
    printf '%s\n' "$line"
done < "$EXAMPLE" > "$TMP"

mv "$TMP" "$ENV_FILE"
trap - EXIT

echo "init-env: created .env from .env.example"
echo "init-env: generated${generated:- nothing}"
remind_openai
