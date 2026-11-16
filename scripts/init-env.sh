#!/usr/bin/env bash
# Creates .env from .env.example when .env is missing, filling each empty secret below
# with a random value. For an existing .env it only appends the keys that .env.example
# has and .env lacks (a generated value for an empty secret, the example value otherwise,
# with the key's comment from .env.example); it never changes or removes a line that is
# already there, so running it again changes nothing. A key counts as there also when its
# line is indented or starts with `export ` (docker compose reads both forms).
# Prints the names of the generated or added keys, never the values. Works with bash 3.2
# (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
EXAMPLE="$ROOT/.env.example"
# Filled only where .env.example leaves the value empty.
SECRETS="JWT_SECRET INTERNAL_API_KEY POSTGRES_PASSWORD MINIO_ROOT_PASSWORD GRAFANA_ADMIN_PASSWORD"

remind_openai() {
    if grep -Eq '^[[:space:]]*(export[[:space:]]+)?OPENAI_API_KEY=$' "$ENV_FILE"; then
        echo "init-env: OPENAI_API_KEY is empty; add it to .env by hand for video moderation"
    fi
}

# value_line LINE: LINE as it goes into .env, a generated value for an empty secret.
# Sets $was_generated to yes or no.
value_line() {
    local line="$1" name="${1%%=*}"
    was_generated=no
    case " $SECRETS " in
        *" $name "*)
            if [ "$line" = "$name=" ]; then
                # Hex: safe inside a database URL and in any shell or YAML context.
                printf '%s=%s\n' "$name" "$(openssl rand -hex 32)"
                was_generated=yes
                return
            fi
            ;;
    esac
    printf '%s\n' "$line"
}

command -v openssl >/dev/null || { echo "init-env: openssl is required" >&2; exit 1; }
[ -f "$EXAMPLE" ] || { echo "init-env: $EXAMPLE not found" >&2; exit 1; }

# Whatever is written below is readable by the owner only.
umask 077
TMP="$(mktemp "$ROOT/.env.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

if [ -f "$ENV_FILE" ]; then
    # Collects the missing keys in $TMP, each after its own comment lines from
    # .env.example, then appends them in one write.
    added=""
    comments=""
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            "#"*) comments="$comments$line"$'\n'; continue ;;
            *=*) ;;
            *) comments=""; continue ;;
        esac
        name="${line%%=*}"
        if ! grep -Eq "^[[:space:]]*(export[[:space:]]+)?$name=" "$ENV_FILE"; then
            {
                printf '\n%s' "$comments"
                value_line "$line"
            } >> "$TMP"
            if [ "$was_generated" = yes ]; then
                added="$added $name (generated)"
            else
                added="$added $name"
            fi
        fi
        comments=""
    done < "$EXAMPLE"
    if [ -z "$added" ]; then
        echo "init-env: keeping existing .env, no key missing"
    else
        # A last line without a newline would run into the first added key.
        if [ -s "$ENV_FILE" ] && [ "$(tail -c 1 "$ENV_FILE" | od -An -c | tr -d ' ')" != '\n' ]; then
            printf '\n' >> "$ENV_FILE"
        fi
        cat "$TMP" >> "$ENV_FILE"
        echo "init-env: keeping existing .env, added from .env.example:$added"
    fi
    remind_openai
    exit 0
fi

generated=""
while IFS= read -r line || [ -n "$line" ]; do
    value_line "$line"
    if [ "$was_generated" = yes ]; then
        generated="$generated ${line%%=*}"
    fi
done < "$EXAMPLE" > "$TMP"

# The new file appears under its final name only when complete.
mv "$TMP" "$ENV_FILE"
trap - EXIT

echo "init-env: created .env from .env.example"
echo "init-env: generated${generated:- nothing}"
remind_openai
