#!/usr/bin/env bash
# Brings Vault (INF-12, module M13) to "unsealed and configured". `make` runs it right
# after `docker compose up -d --wait vault`, before the rest of the stack starts. Vault
# starts sealed after every container start. Five cases, each safe to run again:
# 1. not initialized, no keys file: `vault operator init` (3 key shares, threshold 2)
#    writes its JSON answer straight into scripts/vault-keys.local (mode 600, Git-ignored);
#    then 2 shares unseal Vault and the configuration is applied;
# 2. sealed, keys file present: 2 shares unseal it, then the configuration as in 3;
# 3. unsealed: the configuration is compared and only what differs is written; one line
#    of output when nothing changed;
# 4. initialized but no keys file: stops and says how to get the file back or reset;
# 5. keys file present but Vault not initialized (a new volume): the file is moved to
#    scripts/vault-keys.local.stale-<UTC time>, then as in 1.
# Configuration: the file audit device on stdout (first, so every later request is
# audited), KV v2 at secret/, AppRole, the policies api and worker from
# infra/vault/policies/, the roles api and worker (token TTL 1h, max 4h; secret-ids
# without TTL or use limit). Details: docs/infra/vault.md.
# `--retire-keys` only moves the keys file aside as in 5; `make fclean` runs it after it
# deletes the volumes.
# Talks to Vault only through `docker compose exec -T vault vault ...` (the container sets
# VAULT_ADDR=http://127.0.0.1:8200). Key shares reach Vault on stdin, the root token in
# VAULT_TOKEN of `docker compose exec`; neither is printed or put on a command line.
# Works with bash 3.2 (macOS) and python3 3.9 or newer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
KEYS=scripts/vault-keys.local
POLICIES=infra/vault/policies
ROLES="api worker"

die() {
    echo "vault-init: $*" >&2
    exit 1
}

# Moves the keys file aside: its Vault (the vault-data volume) is gone.
retire_keys() {
    local stale
    stale="$KEYS.stale-$(date -u +%Y%m%dT%H%M%SZ)"
    mv "$KEYS" "$stale"
    echo "vault-init: $KEYS belonged to a Vault that no longer exists; moved to $stale"
}

if [ "${1:-}" = --retire-keys ]; then
    if [ -f "$KEYS" ]; then
        retire_keys
    fi
    exit 0
fi
[ $# -eq 0 ] || die "usage: $0 [--retire-keys]"

command -v python3 >/dev/null || die "python3 is required"
if [ -z "$(docker compose ps -q --status running vault)" ]; then
    die "vault is not running; start the stack with make"
fi

umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# json_get FILE KEY...: the value at FILE's JSON [KEY][KEY]... (a number KEY indexes a
# list); a string as it is, anything else as JSON; nothing when it is missing.
json_get() {
    python3 -c '
import json, sys
try:
    v = json.load(open(sys.argv[1]))
    for k in sys.argv[2:]:
        v = v[int(k)] if isinstance(v, list) else v[k]
except (OSError, ValueError, KeyError, IndexError, TypeError):
    sys.exit(0)
print(v if isinstance(v, str) else json.dumps(v))
' "$@"
}

# The Vault CLI in the container: without a token, or with the root token in VAULT_TOKEN.
# The *_in forms pass this script's stdin on; the others read nothing.
vault_cli() { docker compose exec -T vault vault "$@" </dev/null; }
vault_in() { docker compose exec -T vault vault "$@"; }
vault_root() { VAULT_TOKEN="$root_token" docker compose exec -T -e VAULT_TOKEN vault vault "$@" </dev/null; }
vault_root_in() { VAULT_TOKEN="$root_token" docker compose exec -T -e VAULT_TOKEN vault vault "$@"; }

# Sets $initialized and $sealed (yes / no). `vault status` exits 2 when sealed.
read_status() {
    local rc=0
    vault_cli status -format=json >"$work/status.json" 2>"$work/status.err" || rc=$?
    case "$rc" in
        0 | 2) ;;
        *) die "vault status failed (exit $rc): $(head -n 1 "$work/status.err")" ;;
    esac
    initialized=no
    sealed=yes
    if [ "$(json_get "$work/status.json" initialized)" = true ]; then initialized=yes; fi
    if [ "$(json_get "$work/status.json" sealed)" = false ]; then sealed=no; fi
}

# The commands that give up this Vault and its data, for the messages below.
reset_hint() {
    local volume
    volume="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/vault/file"}}{{.Name}}{{end}}{{end}}' \
        "$(docker compose ps -q vault)" 2>/dev/null || true)"
    cat >&2 <<EOF
  To start over with an empty Vault (everything stored in it is lost):
    docker compose rm --stop --force vault
    docker volume rm ${volume:-<the vault-data volume of this project>}
    make
  See "Reset" in docs/infra/vault.md.
EOF
}

init_vault() {
    vault_cli operator init -key-shares=3 -key-threshold=2 -format=json >"$KEYS" 2>"$work/init.err" || {
        # An empty file holds nothing; anything else is kept, in case it holds keys.
        if [ ! -s "$KEYS" ]; then rm -f "$KEYS"; fi
        die "vault operator init failed: $(head -n 1 "$work/init.err")"
    }
    chmod 600 "$KEYS"
    if [ -z "$(json_get "$KEYS" root_token)" ] || [ -z "$(json_get "$KEYS" unseal_keys_b64 1)" ]; then
        die "$KEYS does not hold the answer of vault operator init; look at it before anything else"
    fi
    echo "vault-init: initialized (3 key shares, threshold 2); key shares and root token in $KEYS (mode 600, Git-ignored)"
}

# Feeds key shares from the keys file, one request each, until the threshold is reached.
unseal() {
    local i=0
    threshold="$(json_get "$KEYS" unseal_threshold)"
    case "$threshold" in
        [1-9]) ;;
        *) die "$KEYS has no unseal_threshold; it is not the answer of vault operator init" ;;
    esac
    # From zero, in case someone entered a share by hand.
    printf '{"reset": true}\n' | vault_in write sys/unseal - >/dev/null 2>&1 || die "could not reset the unseal progress"
    while [ "$i" -lt "$threshold" ]; do
        python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); print(json.dumps({"key": d["unseal_keys_b64"][int(sys.argv[2])]}))' \
            "$KEYS" "$i" | vault_in write sys/unseal - >/dev/null 2>&1 || {
            echo "vault-init: key share $((i + 1)) from $KEYS was refused: the file belongs to another Vault" >&2
            echo "  Put the right file back (an older one may be a $KEYS.stale-* file), or:" >&2
            reset_hint
            exit 1
        }
        i=$((i + 1))
    done
    read_status
    if [ "$sealed" = yes ]; then
        echo "vault-init: Vault is still sealed after $threshold key shares from $KEYS" >&2
        reset_hint
        exit 1
    fi
}

# same_text A B: the two files hold the same text, leading and trailing blanks aside.
same_text() {
    python3 -c 'import sys; a, b = (open(p).read().strip() for p in sys.argv[1:3]); sys.exit(a != b)' "$1" "$2"
}

# role_ok FILE NAME: FILE (`vault read -format=json auth/approle/role/NAME`) shows the
# role as decided.
role_ok() {
    python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))["data"]
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(1)
want = {"token_policies": [sys.argv[2]], "token_ttl": 3600, "token_max_ttl": 14400,
        "secret_id_ttl": 0, "secret_id_num_uses": 0}
sys.exit(any(d.get(k) != v for k, v in want.items()))
' "$1" "$2"
}

# Compares the configuration with what is decided and writes only what differs. Sets
# $changed to the list of what was written.
configure() {
    local p r
    changed=""
    if ! vault_root token lookup >/dev/null 2>&1; then
        echo "vault-init: the root token in $KEYS is refused by this Vault: the file belongs to another one" >&2
        reset_hint
        exit 1
    fi

    vault_root audit list -format=json >"$work/audit.json" 2>/dev/null || : >"$work/audit.json"
    if [ "$(json_get "$work/audit.json" file/ type)" != file ] ||
        [ "$(json_get "$work/audit.json" file/ options file_path)" != stdout ]; then
        if [ -n "$(json_get "$work/audit.json" file/ type)" ]; then
            vault_root audit disable file >/dev/null
        fi
        vault_root audit enable file file_path=stdout >/dev/null
        changed="$changed, audit device file (stdout)"
    fi

    vault_root secrets list -format=json >"$work/mounts.json"
    case "$(json_get "$work/mounts.json" secret/ type)/$(json_get "$work/mounts.json" secret/ options version)" in
        kv/2) ;;
        /)
            vault_root secrets enable -path=secret -version=2 kv >/dev/null
            changed="$changed, KV v2 at secret/"
            ;;
        *) die "secret/ is mounted, but not as KV version 2; see docs/infra/vault.md" ;;
    esac

    vault_root auth list -format=json >"$work/auth.json"
    case "$(json_get "$work/auth.json" approle/ type)" in
        approle) ;;
        "")
            vault_root auth enable approle >/dev/null
            changed="$changed, AppRole"
            ;;
        *) die "approle/ is taken by another auth method; see docs/infra/vault.md" ;;
    esac

    for p in $ROLES; do
        vault_root policy read "$p" >"$work/policy" 2>/dev/null || : >"$work/policy"
        if ! same_text "$work/policy" "$POLICIES/$p.hcl"; then
            vault_root_in policy write "$p" - <"$POLICIES/$p.hcl" >/dev/null
            changed="$changed, policy $p"
        fi
    done

    for r in $ROLES; do
        vault_root read -format=json "auth/approle/role/$r" >"$work/role.json" 2>/dev/null || : >"$work/role.json"
        if ! role_ok "$work/role.json" "$r"; then
            vault_root write "auth/approle/role/$r" token_policies="$r" token_ttl=1h token_max_ttl=4h \
                secret_id_ttl=0 secret_id_num_uses=0 >/dev/null
            changed="$changed, role $r"
        fi
    done
}

read_status
unsealed_now=no
if [ "$initialized" = no ]; then
    if [ -f "$KEYS" ]; then
        retire_keys
    fi
    init_vault
    unseal
    echo "vault-init: unsealed"
    unsealed_now=yes
elif [ ! -f "$KEYS" ]; then
    echo "vault-init: Vault is initialized, but $KEYS is missing; without its key shares and" >&2
    echo "  root token Vault can be neither unsealed nor configured." >&2
    echo "  If the file was moved or renamed, put it back as $KEYS and run make again." >&2
    reset_hint
    exit 1
elif [ "$sealed" = yes ]; then
    unseal
    echo "vault-init: unsealed ($threshold key shares from $KEYS)"
    unsealed_now=yes
fi

root_token="$(json_get "$KEYS" root_token)"
[ -n "$root_token" ] || die "$KEYS has no root_token"
configure
if [ -n "$changed" ]; then
    echo "vault-init: configuration written: ${changed#, }"
elif [ "$unsealed_now" = no ]; then
    echo "vault-init: Vault unsealed, configuration up to date"
else
    echo "vault-init: configuration up to date"
fi
