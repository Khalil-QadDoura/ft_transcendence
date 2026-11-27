#!/usr/bin/env bash
# Creates .env from .env.example when .env is missing. For an existing .env it only appends
# the keys that .env.example has and .env lacks (the example value, with the key's comment
# from .env.example); it never changes or removes a line that is already there, so running
# it again changes nothing. A key counts as there also when its line is indented or starts
# with `export ` (docker compose reads both forms).
# No secret is generated here any more (INF-13): .env holds settings only, the secrets are
# generated in Vault by scripts/vault-init.sh, which also moves into Vault (and removes from
# .env) any secret still found here, OPENAI_API_KEY and FT_CLIENT_SECRET included.
# Prints the names of the added keys, never the values. Works with bash 3.2 (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
EXAMPLE="$ROOT/.env.example"
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
            printf '\n%s%s\n' "$comments" "$line" >> "$TMP"
            added="$added $name"
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
    exit 0
fi

cat "$EXAMPLE" > "$TMP"

# The new file appears under its final name only when complete.
mv "$TMP" "$ENV_FILE"
trap - EXIT

echo "init-env: created .env from .env.example (settings only; make puts the secrets in Vault)"
