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
# audited), KV v2 at secret/, AppRole, the policies api, worker and infra from
# infra/vault/policies/, the roles api, worker and infra (token TTL 1h, max 4h; secret-ids
# without TTL or use limit). Details: docs/infra/vault.md.
# Then the service secrets (INF-13), one KV path per consumer (the inventory in
# secrets_py below); for each secret, in this order:
# - Vault already holds it: kept (a value in .env is then not used);
# - else .env has a non-empty value: moved into Vault, so an existing database volume keeps
#   its password;
# - else a new random value (openssl rand -hex).
# OPENAI_API_KEY and FT_CLIENT_SECRET are typed by hand: a non-empty value in .env always
# replaces the one in Vault. Every value is written to every path that needs it, from that
# one source, and read back; only when the readback matches is the line removed from .env
# (for the two hand-typed ones only the value: `NAME=` stays, ready for the next one). No
# copy of .env is kept. One line per moved key, names only.
# Last, each Vault Agent's AppRole role-id and secret-id, written from inside the vault
# container into the agent's own volume (vault-approle-<role>), so they never reach the host;
# kept while they are valid. When a running agent's secrets or credentials change, the agent
# is restarted (it renders again), then the running services it feeds.
# `--retire-keys` only moves the keys file aside as in 5; `make fclean` runs it after it
# deletes the volumes.
# Talks to Vault only through `docker compose exec -T vault ...` (the container sets
# VAULT_ADDR=http://127.0.0.1:8200). Key shares and secret values reach Vault on stdin, the
# root token in VAULT_TOKEN of `docker compose exec`; none of them is printed or put on a
# command line. Values read from Vault or .env pass through a private temporary directory
# (mode 700, removed on exit).
# Works with bash 3.2 (macOS) and python3 3.9 or newer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
KEYS=scripts/vault-keys.local
POLICIES=infra/vault/policies
ROLES="api worker infra"
ENV_FILE=.env
# The Vault Agent of each role and the long-running services it feeds (INF-13).
agent_of() { echo "vault-agent-$1"; }
consumers_of() {
    case "$1" in
        api) echo "api" ;;
        worker) echo "worker" ;;
        infra) echo "db minio grafana postgres-exporter backup" ;;
    esac
}

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
# vault_root_sh [-u 0] SCRIPT ARG...: SCRIPT run by sh in the vault container, with the root
# token in VAULT_TOKEN; the ARGs are its "$@".
vault_root_sh() {
    local user=()
    if [ "$1" = -u ]; then
        user=(-u "$2")
        shift 2
    fi
    VAULT_TOKEN="$root_token" docker compose exec -T ${user[@]+"${user[@]}"} -e VAULT_TOKEN vault sh -c "$1" sh "${@:2}" </dev/null
}
running() { [ -n "$(docker compose ps -q --status running "$1" 2>/dev/null)" ]; }

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

# The service secrets (INF-13). The inventory is here, in one place: each secret by its
# old .env name, how a missing one is made, and every KV path and field it is written to.
# Commands: paths; plan DUMP ENV OUT; payload PLAN PATH; verify PLAN DUMP; edit-env PLAN ENV.
# A DUMP is the output of read_secrets. Prints names and paths, never a value.
# shellcheck disable=SC2016 # Python source, expanded by nobody
secrets_py='
import json, os, re, subprocess, sys, tempfile

# name: (made by, hex bytes, [(path under secret/, field), ...]); the first path is the
# source of truth, the others copies.
SECRETS = {
    "JWT_SECRET": ("generate", 32, [("api/jwt", "value"), ("worker/jwt", "value")]),
    "INTERNAL_API_KEY": ("generate", 32, [("api/internal-api-key", "value")]),
    "POSTGRES_PASSWORD": ("generate", 32, [
        ("infra/db", "password"), ("api/db", "password"), ("worker/db", "password"),
        ("infra/postgres-exporter", "password"), ("infra/backup", "pg_password")]),
    # MinIO access keys are limited in length: 20 hex characters.
    "MINIO_ROOT_USER": ("generate", 10, [
        ("infra/minio", "root_user"), ("api/minio", "access_key"), ("worker/minio", "access_key"),
        ("infra/backup", "minio_root_user")]),
    "MINIO_ROOT_PASSWORD": ("generate", 32, [
        ("infra/minio", "root_password"), ("api/minio", "secret_key"), ("worker/minio", "secret_key"),
        ("infra/backup", "minio_root_password")]),
    "GRAFANA_ADMIN_PASSWORD": ("generate", 32, [("infra/grafana", "admin_password")]),
    "OPENAI_API_KEY": ("hand", 0, [("worker/openai", "api_key")]),
    "FT_CLIENT_SECRET": ("hand", 0, [("api/oauth42", "client_secret")]),
}
PATHS = sorted({p for _, _, targets in SECRETS.values() for p, _ in targets})
LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def read_env(path):
    values = {}
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        m = LINE.match(line)
        if not m:
            continue
        raw = m.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"\x27":
            raw = raw[1:-1]
        elif " #" in raw:
            raw = raw.split(" #", 1)[0].rstrip()
        values[m.group(1)] = raw
    return values


def read_dump(path):
    found, key, buf = {}, None, []

    def flush():
        if key is None:
            return
        text = "".join(buf).strip()
        data = None
        if text:
            try:
                data = (json.loads(text).get("data") or {}).get("data")
            except (ValueError, AttributeError):
                data = None
        found[key] = data if isinstance(data, dict) else None

    for line in open(path, encoding="utf-8"):
        if line.startswith("@@ "):
            flush()
            key, buf = line[3:].strip(), []
        else:
            buf.append(line)
    flush()
    return found


def paths_of(targets):
    return ", ".join("secret/" + p for p, _ in targets)


cmd = sys.argv[1]
if cmd == "paths":
    print(" ".join(PATHS))
elif cmd == "plan":
    current, env = read_dump(sys.argv[2]), read_env(sys.argv[3])
    desired = {p: {} for p in PATHS}
    env_action, notes, generated = {}, [], []
    for name, (how, size, targets) in SECRETS.items():
        in_vault = None
        for p, field in targets:
            data = current.get(p) or {}
            if field in data and isinstance(data[field], str) and (how == "hand" or data[field]):
                in_vault = data[field]
                break
        from_env = env.get(name, "")
        if how == "hand":
            if from_env:
                value = from_env
                env_action[name] = "blank"
                notes.append(f"{name} moved from .env into Vault ({paths_of(targets)}); its line in .env is now empty")
            else:
                value = in_vault if in_vault is not None else ""
        elif in_vault:
            value = in_vault
            if name in env:
                env_action[name] = "remove"
                notes.append(f"{name} removed from .env: Vault already holds it ({paths_of(targets)}); "
                             "the .env value was not used")
        elif from_env:
            value = from_env
            env_action[name] = "remove"
            notes.append(f"{name} moved from .env into Vault ({paths_of(targets)})")
        else:
            value = subprocess.run(["openssl", "rand", "-hex", str(size)], check=True,
                                   capture_output=True, text=True).stdout.strip()
            if len(value) != 2 * size:
                sys.exit("openssl rand gave no value")
            generated.append(name)
            if name in env:
                env_action[name] = "remove"
        for p, field in targets:
            desired[p][field] = value
    if generated:
        notes.append("generated in Vault: " + ", ".join(generated))
    if not desired["worker/openai"]["api_key"]:
        notes.append("OPENAI_API_KEY is not set, video moderation needs it: put it in .env "
                     "(OPENAI_API_KEY=...) and run make, which moves it into Vault")
    write = [p for p in PATHS if current.get(p) != desired[p]]
    json.dump({"desired": desired, "write": write, "env": env_action, "notes": notes,
               "roles": sorted({p.split("/")[0] for p in write})}, open(sys.argv[4], "w"))
elif cmd == "payload":
    plan = json.load(open(sys.argv[2]))
    print(json.dumps({"data": plan["desired"][sys.argv[3]]}))
elif cmd == "verify":
    plan, current = json.load(open(sys.argv[2])), read_dump(sys.argv[3])
    bad = [p for p, want in plan["desired"].items() if current.get(p) != want]
    if bad:
        sys.exit("readback differs at " + ", ".join("secret/" + p for p in bad))
elif cmd == "edit-env":
    plan, path = json.load(open(sys.argv[2])), sys.argv[3]
    actions = plan["env"]
    if not actions:
        sys.exit(0)
    out, blanked = [], set()
    for line in open(path, encoding="utf-8").read().splitlines(keepends=True):
        m = LINE.match(line)
        action = actions.get(m.group(1)) if m else None
        if action == "remove":
            continue
        if action == "blank":
            if m.group(1) not in blanked:
                out.append(m.group(1) + "=\n")
                blanked.add(m.group(1))
            continue
        out.append(line)
    mode = os.stat(path).st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".env.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(out)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
'

# read_secrets FILE: every inventory path of KV secret/ into FILE, each after a line
# "@@ <path>"; nothing after it when the path does not exist.
read_secrets() {
    # shellcheck disable=SC2046 # one word per path
    vault_root_sh 'for p; do echo "@@ $p"; vault kv get -format=json "secret/$p" 2>/dev/null || true; done' \
        $(python3 -c "$secrets_py" paths) >"$1" || die "could not read the secrets from Vault"
}

# Sets $secret_roles to the roles whose secrets were written (for the restarts below).
sync_secrets() {
    local p n
    secret_roles=""
    read_secrets "$work/before"
    python3 -c "$secrets_py" plan "$work/before" "$ENV_FILE" "$work/plan.json" || die "could not plan the secrets"
    n=0
    for p in $(json_get "$work/plan.json" write | python3 -c 'import json, sys; print(" ".join(json.load(sys.stdin)))'); do
        python3 -c "$secrets_py" payload "$work/plan.json" "$p" |
            vault_root_in write "secret/data/$p" - >/dev/null || die "could not write secret/$p"
        n=$((n + 1))
    done
    read_secrets "$work/after"
    python3 -c "$secrets_py" verify "$work/plan.json" "$work/after" ||
        die "the secrets read back from Vault differ from what was written; .env left unchanged"
    python3 -c "$secrets_py" edit-env "$work/plan.json" "$ENV_FILE" || die "could not update $ENV_FILE"
    json_get "$work/plan.json" notes | python3 -c 'import json, sys; [print("vault-init: " + n) for n in json.load(sys.stdin)]'
    if [ "$n" -gt 0 ]; then
        changed="$changed, $n secret paths"
        secret_roles="$(json_get "$work/plan.json" roles | python3 -c 'import json, sys; print(" ".join(json.load(sys.stdin)))')"
    fi
}

# Each role's role-id and secret-id into /vault/approle/<role> (the volume
# vault-approle-<role>), as root inside the vault container, readable by the agent's uid 100
# only. A secret-id is kept while Vault still knows it (lookup); else a new one, without TTL
# or use limit, as the role says. Prints "<role> kept" or "<role> written" per role.
# shellcheck disable=SC2016 # runs in the container
approle_sh='set -eu
for r; do
    d="/vault/approle/$r"
    [ -d "$d" ] || { echo "$d is not mounted" >&2; exit 1; }
    state=kept
    rid="$(vault read -field=role_id "auth/approle/role/$r/role-id")"
    if [ "$(cat "$d/role-id" 2>/dev/null || true)" != "$rid" ]; then
        printf "%s" "$rid" >"$d/role-id.new"
        mv "$d/role-id.new" "$d/role-id"
        state=written
    fi
    if [ -s "$d/secret-id" ] && printf "{\"secret_id\": \"%s\"}" "$(cat "$d/secret-id")" |
        vault write -field=secret_id_accessor "auth/approle/role/$r/secret-id/lookup" - >/dev/null 2>&1; then
        :
    else
        vault write -f -field=secret_id "auth/approle/role/$r/secret-id" >"$d/secret-id.new"
        mv "$d/secret-id.new" "$d/secret-id"
        state=written
    fi
    chown 100:1000 "$d" "$d/role-id" "$d/secret-id"
    chmod 500 "$d"
    chmod 400 "$d/role-id" "$d/secret-id"
    echo "$r $state"
done'

# Sets $approle_roles to the roles whose credentials were written.
sync_approle() {
    local r state
    approle_roles=""
    # shellcheck disable=SC2086 # one word per role
    vault_root_sh -u 0 "$approle_sh" $ROLES >"$work/approle" || die "could not write the AppRole credentials of the agents"
    while read -r r state; do
        if [ "$state" = written ]; then approle_roles="$approle_roles $r"; fi
    done <"$work/approle"
    if [ -n "$approle_roles" ]; then
        changed="$changed, AppRole credentials of$(for r in $approle_roles; do printf ' %s' "$(agent_of "$r")"; done)"
    fi
}

# A running agent whose secrets or credentials changed renders again; then the running
# services it feeds restart, so they read the new values.
restart_agents() {
    local r a c seen=" "
    for r in $secret_roles $approle_roles; do
        case "$seen" in *" $r "*) continue ;; esac
        seen="$seen$r "
        a="$(agent_of "$r")"
        running "$a" || continue
        echo "vault-init: restarting $a, it renders the new values"
        docker compose restart "$a" >/dev/null
        docker compose up -d --no-deps --no-recreate --wait --wait-timeout 120 "$a" >/dev/null 2>&1 ||
            die "$a did not render its files; see docker compose logs $a"
        case " $secret_roles " in *" $r "*) ;; *) continue ;; esac
        for c in $(consumers_of "$r"); do
            if running "$c"; then
                echo "vault-init: restarting $c, it reads its secrets at start"
                docker compose restart "$c" >/dev/null
            fi
        done
    done
}

# The health of a service's container: healthy, starting, unhealthy, or nothing.
health_of() {
    docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
        "$(docker compose ps -q "$1")" 2>/dev/null || true
}

# After a Docker or host restart (every container started at once, Vault sealed) or with
# Vault stopped for a while, the agents and the services waiting on them are already marked
# unhealthy when Vault gets unsealed. Docker checks them again only every 30 s, and
# `up --wait` gives up at once on an unhealthy dependency, so the first `make` would fail.
# So: every running agent that is not healthy restarts (its health starts again from
# "starting") and every running agent must turn healthy; then every other running service
# that is not healthy (it waited on its secrets) is stopped and started again in dependency
# order, each waiting for the health of what it depends on. Nothing happens when every
# running agent is healthy (a normal `make`), nor before the agents exist (a first `make`).
wake_waiting() {
    local r a agents="" services
    for r in $ROLES; do
        a="$(agent_of "$r")"
        [ -n "$(docker compose ps -q --status running --status restarting "$a" 2>/dev/null)" ] || continue
        [ "$(health_of "$a")" = healthy ] || agents="$agents $a"
    done
    [ -n "$agents" ] || return 0
    echo "vault-init: restarting$agents, not healthy yet after the unseal"
    # shellcheck disable=SC2086 # one word per service
    docker compose restart $agents >/dev/null
    for r in $ROLES; do
        a="$(agent_of "$r")"
        running "$a" || continue
        docker compose up -d --no-deps --no-recreate --wait --wait-timeout 120 "$a" >/dev/null 2>"$work/wake.err" ||
            die "$(docker compose ps -a --format '{{.Name}}' "$a") did not get healthy within 120 s ($(tail -n 1 "$work/wake.err")); see docker compose logs $a"
    done
    services="$(docker compose ps --status running --format '{{.Service}} {{.Health}}' |
        awk '$1 != "vault" && $1 !~ /^vault-agent-/ && ($2 == "unhealthy" || $2 == "starting") { print $1 }' |
        sort | xargs)"
    [ -n "$services" ] || return 0
    echo "vault-init: restarting $services, they waited on their secrets"
    # shellcheck disable=SC2086 # one word per service
    docker compose stop $services >/dev/null 2>&1
    # shellcheck disable=SC2086
    docker compose up -d --no-recreate --wait --wait-timeout 300 $services >/dev/null 2>"$work/wake.err" ||
        die "not healthy after the restart: $(tail -n 1 "$work/wake.err"); see docker compose ps"
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
sync_secrets
sync_approle
restart_agents
wake_waiting
if [ -n "$changed" ]; then
    echo "vault-init: configuration written: ${changed#, }"
elif [ "$unsealed_now" = no ]; then
    echo "vault-init: Vault unsealed, configuration up to date"
else
    echo "vault-init: configuration up to date"
fi
