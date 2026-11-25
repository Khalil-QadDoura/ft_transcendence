#!/usr/bin/env bash
# Smoke test of Vault (INF-12, module M13) against the running stack, from the host. Vault
# has no host port: every request goes through `docker compose exec -T vault vault ...`.
# - Vault is initialized and unsealed: Shamir seal, 3 key shares, threshold 2;
# - the root token in scripts/vault-keys.local is accepted;
# - server mode, not dev mode: storage "file", the server process started as
#   `vault server -config=...` without any -dev flag, UI off;
# - Vault runs as a non-root user with mlock on and its memory locked (VmLck above 0);
# - KV version 2 at secret/, AppRole at approle/;
# - the roles api, worker and infra: the role's own policy, token TTL 1h, max 4h, secret-ids
#   without TTL or use limit; the policies api, worker and infra in Vault are the files in
#   infra/vault/policies/; the audit device file/ writes to stdout (the container log);
# - isolation: the root token writes a random throwaway value to secret/<role>/vault-check
#   for each role (KV v2 API paths secret/data/<role>/vault-check); each role logs in with
#   its role-id and a new one-use secret-id; its token reads its own value, gets 403 reading
#   each other role's and 403 writing its own;
# - the service secrets (INF-13): every KV path of the inventory exists with its fields set
#   (OPENAI_API_KEY and FT_CLIENT_SECRET may be empty); each role token reads its own real
#   paths and gets 403 on the others' (api cannot read worker or infra paths, infra cannot
#   read api paths); values are only compared, never printed;
# - the three Vault Agents run, are healthy, and every file they render exists and is not
#   empty; each rendered-secrets volume is tmpfs, mounted read-write by its agent only and
#   read-only by its one service only; each AppRole volume only by vault and its agent;
# - no secret NAME in .env (only OPENAI_API_KEY= and FT_CLIENT_SECRET= with no value), no
#   secret name in the environment compose gives any container (docker inspect), and the
#   api and worker processes have their secrets set (names and set / not set only);
# - the audit log (the vault container log) holds these requests of each role's token,
#   found by the token's HMAC (sys/audit-hash/file), the denied ones included; none of this
#   run's tokens, accessors, role-ids, secret-ids or values appears in clear, and the whole
#   vault log has no token in clear (no "hvs.");
# - clean-up, checked afterwards: the values deleted with their metadata, the role tokens
#   revoked, their secret-ids gone (used up by the login, then destroyed); this also runs
#   when the check fails or is interrupted;
# - scripts/vault-keys.local is Git-ignored, not tracked, mode 600, and no
#   scripts/*.local* file is tracked;
# - the vault container publishes no host port, and no proxy template routes to vault.
# Prints one ok / FAIL line per check, then exits 1 when one failed.
# The root token is read from scripts/vault-keys.local into memory and reaches Vault in
# VAULT_TOKEN of `docker compose exec`, as do the role tokens; role-ids, secret-ids and the
# values go on stdin. Nothing secret is printed or put on a command line.
# Needs the stack up (`make`). Run it with `make vault-check`. Works with bash 3.2 (macOS)
# and python3 3.9 or newer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ -z "$(docker compose ps -q --status running vault)" ]; then
    echo "vault-check: vault is not running; start the stack with make" >&2
    exit 1
fi
echo "vault-check: Vault inside the vault container (no host port), root token from scripts/vault-keys.local"

python3 - <<'PY'
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time

KEYS = "scripts/vault-keys.local"
POLICIES = "infra/vault/policies"
ROLES = ("api", "worker", "infra")
ROLE_LIST = "{" + ",".join(ROLES) + "}"
NAME = "vault-check"  # the throwaway secret of each role: secret/<role>/vault-check
# The roles as decided (scripts/vault-init.sh writes them so).
ROLE = {"token_ttl": 3600, "token_max_ttl": 14400, "secret_id_ttl": 0, "secret_id_num_uses": 0}
# The service secrets as scripts/vault-init.sh writes them (INF-13): KV path under secret/ ->
# its fields; the hand-typed ones may be empty.
SECRET_PATHS = {
    "api/jwt": ["value"], "api/internal-api-key": ["value"], "api/db": ["password"],
    "api/minio": ["access_key", "secret_key"], "api/oauth42": ["client_secret"],
    "worker/jwt": ["value"], "worker/db": ["password"], "worker/minio": ["access_key", "secret_key"],
    "worker/openai": ["api_key"],
    "infra/db": ["password"], "infra/minio": ["root_user", "root_password"],
    "infra/grafana": ["admin_password"], "infra/postgres-exporter": ["password"],
    "infra/backup": ["pg_password", "minio_root_user", "minio_root_password"],
}
MAY_BE_EMPTY = {("api/oauth42", "client_secret"), ("worker/openai", "api_key")}
# Each Vault Agent: its role, the files it renders, and which service reads which volume.
AGENTS = {
    "vault-agent-api": ("api", ["api/env", "api-test/env"]),
    "vault-agent-worker": ("worker", ["worker/env"]),
    "vault-agent-infra": ("infra", ["db/postgres-password", "minio/root-user", "minio/root-password",
                                    "minio-init/env", "grafana/admin-password",
                                    "postgres-exporter/password", "backup/env"]),
}
CONSUMER = {"secrets-api": "api", "secrets-api-test": "api-test", "secrets-worker": "worker",
            "secrets-db": "db", "secrets-minio": "minio", "secrets-minio-init": "minio-init",
            "secrets-grafana": "grafana", "secrets-postgres-exporter": "postgres-exporter",
            "secrets-backup": "backup"}
WRITER = {vol: agent for agent, (_, files) in AGENTS.items() for vol in {"secrets-" + f.split("/")[0] for f in files}}
# Secret names that must not be in .env (moved into Vault), nor in any container's environment.
ENV_FILE_SECRETS = ["JWT_SECRET", "INTERNAL_API_KEY", "POSTGRES_PASSWORD", "MINIO_ROOT_USER",
                    "MINIO_ROOT_PASSWORD", "GRAFANA_ADMIN_PASSWORD"]
HAND_SECRETS = ["OPENAI_API_KEY", "FT_CLIENT_SECRET"]
CONTAINER_SECRETS = ENV_FILE_SECRETS + HAND_SECRETS + [
    "DATABASE_URL", "TEST_DATABASE_URL", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "PGPASSWORD",
    "GF_SECURITY_ADMIN_PASSWORD", "DATA_SOURCE_PASS", "VAULT_TOKEN"]
# What each app process must have set (the second list may be empty: typed by hand).
PROCESS_ENV = {
    "api": (["JWT_SECRET", "INTERNAL_API_KEY", "DATABASE_URL", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"],
            ["FT_CLIENT_SECRET"]),
    "worker": (["JWT_SECRET", "DATABASE_URL", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"], ["OPENAI_API_KEY"]),
}
failures = 0

# SIGTERM ends the check like Ctrl-C does: through the clean-up below.
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))


def report(ok, text):
    global failures
    if not ok:
        failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {text}", flush=True)


def run(cmd, stdin="", env=None):
    """(exit code, stdout, stderr) of a host command; -1 when it cannot run."""
    try:
        done = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env, timeout=120)
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, "", str(error)


def vault(*args, token=None, stdin=""):
    """(exit code, stdout, stderr) of `vault ARGS` in the vault container. A token goes in
    VAULT_TOKEN of `docker compose exec`, never on a command line."""
    env = dict(os.environ)
    env.pop("VAULT_TOKEN", None)
    cmd = ["docker", "compose", "exec", "-T"]
    if token:
        env["VAULT_TOKEN"] = token
        cmd += ["-e", "VAULT_TOKEN"]
    return run(cmd + ["vault", "vault", *args], stdin=stdin, env=env)


def as_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def data_of(text):
    """The "data" object of a `vault ... -format=json` answer; {} when there is none."""
    answer = as_json(text)
    data = answer.get("data") if isinstance(answer, dict) else None
    return data if isinstance(data, dict) else {}


def why(err):
    """The last line of a Vault CLI error, e.g. "* permission denied"."""
    lines = [line.strip() for line in err.splitlines() if line.strip()]
    return lines[-1][:120] if lines else "no answer"


def denied(rc, err):
    return rc != 0 and "Code: 403" in err


RULE = re.compile(r'path\s+"([^"]+)"\s*\{[^}]*?capabilities\s*=\s*\[([^\]]*)\]', re.S)


def rules(text):
    """'read on secret/data/api/*' for each path rule of a policy."""
    found = []
    for path, caps in RULE.findall(text):
        found.append(", ".join(c.strip().strip('"') for c in caps.split(",") if c.strip()) + " on " + path)
    return "; ".join(found) or "no path rule"


# --- State --------------------------------------------------------------------------------
rc, out, err = vault("status", "-format=json")
status = as_json(out) if rc in (0, 2) else None
status = status if isinstance(status, dict) else {}
unsealed = status.get("initialized") is True and status.get("sealed") is False
state = ("initialized" if status.get("initialized") else "not initialized") + ", " + (
    "unsealed" if status.get("sealed") is False else "sealed")
report(unsealed and status.get("type") == "shamir" and status.get("n") == 3 and status.get("t") == 2,
       f"Vault {status.get('version')}: {state}; {status.get('type')} seal, {status.get('n')} key shares, "
       f"threshold {status.get('t')}"
       + ("" if rc in (0, 2) else f" (vault status: {why(err)})")
       + ("" if unsealed else "; make initializes and unseals it"))

root = None
try:
    with open(KEYS, encoding="utf-8") as f:
        root = json.load(f).get("root_token") or None
except (OSError, ValueError, AttributeError):
    pass
root_ok = False
if root is None:
    report(False, f"{KEYS} missing or without a root token (make writes it on the first run)")
elif unsealed:
    rc, out, err = vault("token", "lookup", "-format=json", token=root)
    root_ok = rc == 0 and "root" in (data_of(out).get("policies") or [])
    report(root_ok, f"root token from {KEYS} accepted" + ("" if root_ok else f": {why(err)}"))

creds = {role: {} for role in ROLES}
values = {role: f"{NAME}-{secrets.token_hex(16)}" for role in ROLES}
if not (unsealed and root_ok):
    report(False, "configuration, isolation and audit log not checked: Vault sealed or root token missing")
else:
    # --- Server mode ----------------------------------------------------------------------
    rc, out, err = vault("read", "-format=json", "sys/config/state/sanitized", token=root)
    config = data_of(out)
    # The server process: its command line, user and locked memory, from /proc.
    proc = r'''for d in /proc/[0-9]*; do
      c="$(tr "\0" " " <"$d/cmdline" 2>/dev/null)"
      case "$c" in "vault server "*) echo "cmd $c"; grep -E "^(Uid|VmLck):" "$d/status" ;; esac
    done'''
    rc, out, err = run(["docker", "compose", "exec", "-T", "vault", "sh", "-c", proc])
    cmdline, uids, locked = "", [], -1
    for line in out.splitlines():
        if line.startswith("cmd "):
            cmdline = line[4:].strip()
        elif line.startswith("Uid:"):
            uids = line.split()[1:]
        elif line.startswith("VmLck:") and len(line.split()) > 1 and line.split()[1].isdigit():
            locked = int(line.split()[1])
    dev = " -dev" in f" {cmdline}"
    storage = (config.get("storage") or {}).get("type")
    report(status.get("storage_type") == "file" and storage == "file" and cmdline.startswith("vault server ")
           and not dev and config.get("enable_ui") is False,
           f"server mode: storage {status.get('storage_type')}, process \"{cmdline or '(not found)'}\" "
           + ("WITH a -dev flag" if dev else "(no -dev)")
           + f", UI {'off' if config.get('enable_ui') is False else 'on or unknown'}")
    nonroot = bool(uids) and all(uid != "0" for uid in uids)
    report(nonroot and config.get("disable_mlock") is False and locked > 0,
           f"runs as uid {uids[1] if len(uids) > 1 else '?'}" + (" (not root)" if nonroot else " (root)")
           + f"; mlock {'on' if config.get('disable_mlock') is False else 'off'}, "
           + ("memory locked (VmLck above 0)" if locked > 0 else "no memory locked (VmLck 0)" if locked == 0
              else "locked memory unknown"))

    # --- Engines, roles, policies, audit device ------------------------------------------
    rc, out, err = vault("secrets", "list", "-format=json", token=root)
    mount = (as_json(out) or {}).get("secret/") or {}
    version = (mount.get("options") or {}).get("version")
    report(mount.get("type") == "kv" and version == "2",
           f"secrets engine at secret/: {mount.get('type') or 'none'}" + (f" version {version}" if version else ""))
    rc, out, err = vault("auth", "list", "-format=json", token=root)
    method = ((as_json(out) or {}).get("approle/") or {}).get("type")
    report(method == "approle", f"auth method at approle/: {method or 'none'}")
    for role in ROLES:
        rc, out, err = vault("read", "-format=json", f"auth/approle/role/{role}", token=root)
        data = data_of(out)
        wrong = [f"{k} {data.get(k)} (decided {v})" for k, v in ROLE.items() if data.get(k) != v]
        if data.get("token_policies") != [role]:
            wrong.insert(0, f"token_policies {data.get('token_policies')} (decided ['{role}'])")
        report(rc == 0 and not wrong,
               f"role {role}: " + ("; ".join(wrong) if rc == 0 and wrong else why(err) if rc else
                                   f"token policy {role}, token TTL 1h, max 4h; secret-ids without TTL or use limit"))
    for role in ROLES:
        rc, out, err = vault("policy", "read", role, token=root)
        try:
            with open(f"{POLICIES}/{role}.hcl", encoding="utf-8") as f:
                wanted = f.read()
        except OSError:
            wanted = None
        same = rc == 0 and wanted is not None and out.strip() == wanted.strip()
        report(same, f"policy {role} in Vault " + ("= " if same else "differs from ")
               + f"{POLICIES}/{role}.hcl: " + (rules(out) if rc == 0 else why(err)))
    rc, out, err = vault("audit", "list", "-format=json", token=root)
    device = (as_json(out) or {}).get("file/") or {} if rc == 0 else {}
    target = (device.get("options") or {}).get("file_path")
    report(device.get("type") == "file" and target == "stdout",
           "audit device file/: " + (f"{device.get('type')} to {target} (the vault container log)" if device
                                     else "none enabled"))

    # --- Isolation, audit log, clean-up -------------------------------------------------
    try:
        written = 0
        for role in ROLES:
            rc, _, err = vault("write", f"secret/data/{role}/{NAME}", "-", token=root,
                               stdin=json.dumps({"data": {"value": values[role]}}))
            written += rc == 0
        report(written == len(ROLES),
               f"root token writes a random throwaway value to secret/data/{ROLE_LIST}/{NAME}"
               + ("" if written == len(ROLES) else f": {why(err)}"))
        for role in ROLES:
            mine = creds[role]
            rc, out, err = vault("read", "-format=json", f"auth/approle/role/{role}/role-id", token=root)
            mine["role_id"] = data_of(out).get("role_id")
            rc, out, err = vault("write", "-format=json", "-f", f"auth/approle/role/{role}/secret-id",
                                 "num_uses=1", "ttl=300", token=root)
            data = data_of(out)
            mine["secret_id"], mine["accessor"] = data.get("secret_id"), data.get("secret_id_accessor")
            rc, out, err = vault("write", "-format=json", "auth/approle/login", "-",
                                 stdin=json.dumps({"role_id": mine["role_id"], "secret_id": mine["secret_id"]}))
            auth = (as_json(out) or {}).get("auth") or {} if rc == 0 else {}
            mine["token"], mine["token_accessor"] = auth.get("client_token"), auth.get("accessor")
            policies = sorted(auth.get("token_policies") or [])
            report(bool(mine["token"]) and policies == sorted(["default", role]),
                   f"{role}: AppRole login with its role-id and a one-use secret-id"
                   + (f"; token policies {', '.join(policies)}, TTL {auth.get('lease_duration')} s"
                      if mine["token"] else f": {why(err)}"))
        for role in ROLES:
            token = creds[role].get("token")
            if not token:
                report(False, f"{role} token: none, isolation not checked")
                continue
            rc, out, err = vault("read", "-format=json", f"secret/data/{role}/{NAME}", token=token)
            got = (data_of(out).get("data") or {}).get("value")
            report(rc == 0 and got == values[role],
                   f"{role} token reads its own secret/data/{role}/{NAME}"
                   + ("" if rc == 0 else f": {why(err)}") + (" (another value)" if rc == 0 and got != values[role] else ""))
            for other in (r for r in ROLES if r != role):
                rc, out, err = vault("read", f"secret/data/{other}/{NAME}", token=token)
                report(denied(rc, err), f"{role} token gets 403 reading secret/data/{other}/{NAME}"
                       + ("" if rc else f": ALLOWED, policy {role} reaches beyond secret/data/{role}/*")
                       + ("" if rc == 0 or denied(rc, err) else f": {why(err)}"))
            rc, out, err = vault("write", f"secret/data/{role}/{NAME}", "-", token=token,
                                 stdin=json.dumps({"data": {"value": "overwritten-by-" + role}}))
            report(denied(rc, err), f"{role} token gets 403 writing its own secret/data/{role}/{NAME}"
                   + ("" if rc else ": ALLOWED") + ("" if rc == 0 or denied(rc, err) else f": {why(err)}"))

        # The real service secrets (INF-13): all there, and each role reaches only its own.
        # Values stay in memory: only compared, never printed.
        missing = []
        for path, fields in SECRET_PATHS.items():
            rc, out, err = vault("read", "-format=json", f"secret/data/{path}", token=root)
            data = data_of(out).get("data") or {} if rc == 0 else {}
            for field in fields:
                value = data.get(field)
                if not isinstance(value, str) or (not value and (path, field) not in MAY_BE_EMPTY):
                    missing.append(f"secret/{path} {field}")
        hand_empty = []
        for path, field in sorted(MAY_BE_EMPTY):
            rc, out, err = vault("read", "-format=json", f"secret/data/{path}", token=root)
            if not (data_of(out).get("data") or {}).get(field):
                hand_empty.append(f"secret/{path}")
        report(not missing, f"service secrets: the {len(SECRET_PATHS)} KV paths of the inventory, every field set"
               + (f"; MISSING or empty: {', '.join(missing)}" if missing else "")
               + (f" (hand-typed, still empty: {', '.join(hand_empty)})" if hand_empty else ""))
        for role in ROLES:
            token = creds[role].get("token")
            if not token:
                continue
            own_ok, foreign_open = [], []
            for path in SECRET_PATHS:
                rc, out, err = vault("read", "-format=json", f"secret/data/{path}", token=token)
                if path.startswith(role + "/"):
                    own_ok.append(rc == 0)
                elif not denied(rc, err):
                    foreign_open.append(f"secret/{path}")
            others = "/".join(r for r in ROLES if r != role)
            report(all(own_ok) and own_ok and not foreign_open,
                   f"{role} token reads its {len(own_ok)} real paths secret/{role}/*"
                   + ("" if all(own_ok) else " (NOT all)")
                   + f" and gets 403 on every {others} path"
                   + (f"; READABLE: {', '.join(foreign_open)}" if foreign_open else ""))

        # Each role token's requests in the audit log, found by the token's HMAC.
        hashes = {}
        for role in ROLES:
            token = creds[role].get("token")
            if token:
                rc, out, err = vault("write", "-format=json", "sys/audit-hash/file", "-", token=root,
                                     stdin=json.dumps({"input": token}))
                hashes[role] = data_of(out).get("hash")

        def seen(log):
            found = {role: {"read": False, "denied read": False, "denied write": False} for role in ROLES}
            for line in log.splitlines():
                entry = as_json(line.strip())
                if not isinstance(entry, dict) or not isinstance(entry.get("request"), dict):
                    continue
                request, auth = entry["request"], entry.get("auth") or {}
                for role in ROLES:
                    h = hashes.get(role)
                    if not h or h not in (auth.get("client_token"), request.get("client_token")):
                        continue
                    others = [f"secret/data/{r}/{NAME}" for r in ROLES if r != role]
                    path, op = request.get("path"), request.get("operation")
                    refused = "permission denied" in str(entry.get("error") or "")
                    if path == f"secret/data/{role}/{NAME}" and op == "read" and not refused:
                        found[role]["read"] = True
                    elif path in others and op == "read" and refused:
                        found[role]["denied read"] = True
                    elif path == f"secret/data/{role}/{NAME}" and op in ("create", "update") and refused:
                        found[role]["denied write"] = True
            return found

        deadline = time.time() + 15
        while True:
            rc, log, err = run(["docker", "compose", "logs", "--no-log-prefix", "--no-color", "vault"])
            found = seen(log)
            if all(all(f.values()) for f in found.values()) or time.time() > deadline:
                break
            time.sleep(1)
        for role in ROLES:
            missing = [k for k, v in found[role].items() if not v]
            report(bool(hashes.get(role)) and not missing,
                   f"audit log: {role} token's requests (read own; read other, write own: permission denied), "
                   "token as HMAC" + (f"; missing: {', '.join(missing)}" if missing and hashes.get(role) else
                                      "" if hashes.get(role) else "; no HMAC from sys/audit-hash/file"))
        plain = [root] + list(values.values()) + [
            v for mine in creds.values()
            for v in (mine.get(k) for k in ("role_id", "secret_id", "accessor", "token", "token_accessor")) if v]
        leaked = sum(1 for v in plain if v in log)
        report(rc == 0 and leaked == 0,
               f"audit log: none of this run's {len(plain)} credentials and values in clear "
               "(root and role tokens, accessors, role-ids, secret-ids, values)"
               + (f"; {leaked} found in clear" if leaked else ""))
        report(rc == 0 and "hvs." not in log, 'whole vault log: no token in clear (no "hvs.")')
    finally:
        for role in ROLES:
            mine = creds[role]
            if mine.get("token"):
                vault("token", "revoke", "-self", token=mine["token"])
            if mine.get("accessor"):
                vault("write", f"auth/approle/role/{role}/secret-id-accessor/destroy", "-", token=root,
                      stdin=json.dumps({"secret_id_accessor": mine["accessor"]}))
            vault("delete", f"secret/metadata/{role}/{NAME}", token=root)

    # Vault answers 404 for what does not exist; the CLI prints "No value found" and exits 2.
    def absent(rc, out, err):
        return rc == 2 and "No value found" in out + err

    gone = [absent(*vault("read", f"secret/data/{role}/{NAME}", token=root)) for role in ROLES]
    report(all(gone), f"clean-up: secret/data/{ROLE_LIST}/{NAME} deleted with their metadata")
    revoked = []
    for role in ROLES:
        if creds[role].get("token"):
            rc, out, err = vault("token", "lookup", token=creds[role]["token"])
            revoked.append(denied(rc, err))
    report(len(revoked) == len(ROLES) and all(revoked), "clean-up: every role token revoked (a lookup with it gets 403)")
    # The role's secret-id accessors; with -format=json an empty list is {} and exit code 2
    # (the table format says "No value found" instead).
    left = []
    for role in ROLES:
        rc, out, err = vault("list", "-format=json", f"auth/approle/role/{role}/secret-id", token=root)
        listed = as_json(out) if rc == 0 else [] if rc == 2 and as_json(out) == {} else None
        if not creds[role].get("accessor") or not isinstance(listed, list) or creds[role]["accessor"] in listed:
            left.append(role)
    report(not left, "clean-up: every one-use secret-id gone (used up by the login, then destroyed)"
           + (f"; still there or never made: {', '.join(left)}" if left else ""))

# --- Vault Agents, rendered secrets, .env (INF-13) -------------------------------------------
def compose_out(*args):
    rc, out, err = run(["docker", "compose", *args])
    return out if rc == 0 else ""


for agent, (role, files) in AGENTS.items():
    cid = compose_out("ps", "-q", "--status", "running", agent).strip()
    health = ""
    if cid:
        rc, out, err = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", cid])
        health = out.strip()
    empty = []
    if cid:
        # /tmp/rendered: the agent's private marker, rendered once this run of the agent has
        # read every one of its paths (removed at its start; the rendered files are kept).
        for f in ["/tmp/rendered"] + [f"/out/{f}" for f in files]:
            rc, _, _ = run(["docker", "compose", "exec", "-T", agent, "test", "-s", f])
            if rc != 0:
                empty.append(f.replace("/out/", "", 1))
    report(bool(cid) and health == "healthy" and not empty,
           f"{agent} (AppRole {role}): " + ("running" if cid else "NOT running") + f", health {health or '?'}; "
           + (f"rendered {len(files)} non-empty file{'s' if len(files) != 1 else ''} ({', '.join(files)})" if not empty
              else f"MISSING or empty: {', '.join(empty)}"))

# MinIO started without its *_FILE files falls back to minioadmin:minioadmin, publicly known
# credentials, and /files reaches MinIO's S3 API through the proxy. Those must be refused.
# The credentials go in MC_HOST_* (public defaults, not a secret), nothing is written.
cid = compose_out("ps", "-q", "--status", "running", "minio").strip()
if cid:
    rc, out, err = run(["docker", "exec", "-e", "MC_HOST_vaultcheck=http://minioadmin:minioadmin@localhost:9000",
                        cid, "mc", "ls", "vaultcheck"])
    report(rc != 0, "minio refuses the default credentials minioadmin:minioadmin (its root user and password come from Vault)"
           + ("" if rc != 0 else "; ACCEPTED: MinIO started without its secret files, restart it: docker compose restart minio"))
else:
    report(False, "minio refuses the default credentials: minio is NOT running")

# Every container of this project (one-offs included): its service, mounts and environment.
ids = compose_out("ps", "-a", "-q").split()
rc, out, err = run(["docker", "inspect", *ids]) if ids else (1, "", "no container")
containers = as_json(out) if rc == 0 else []
mounts, env_names, project = {}, {}, ""
for c in containers or []:
    labels = (c.get("Config") or {}).get("Labels") or {}
    service, project = labels.get("com.docker.compose.service", "?"), labels.get("com.docker.compose.project", project)
    for m in c.get("Mounts") or []:
        if m.get("Type") == "volume":
            mounts.setdefault(m.get("Name", ""), []).append((service, bool(m.get("RW"))))
    env_names[service] = {e.split("=", 1)[0] for e in (c.get("Config") or {}).get("Env") or []}
prefix = project + "_"
wrong, not_tmpfs = [], []
for vol, consumer in CONSUMER.items():
    users = sorted(set(mounts.get(prefix + vol, [])))
    allowed = {(WRITER[vol], True), (consumer, False)}
    if any(u not in allowed for u in users) or (WRITER[vol], True) not in users:
        wrong.append(f"{vol}: " + (", ".join(f"{s} {'rw' if w else 'ro'}" for s, w in users) or "unused"))
    rc, out, err = run(["docker", "volume", "inspect", "-f", "{{index .Options \"type\"}}", prefix + vol])
    if out.strip() != "tmpfs":
        not_tmpfs.append(vol)
report(not wrong and not not_tmpfs,
       f"rendered-secret volumes: {len(CONSUMER)} tmpfs volumes, each written by its agent only and read-only "
       "by its one service only"
       + (f"; WRONG: {'; '.join(wrong)}" if wrong else "") + (f"; NOT tmpfs: {', '.join(not_tmpfs)}" if not_tmpfs else ""))
wrong = []
for agent, (role, _) in AGENTS.items():
    vol = f"vault-approle-{role}"
    users = sorted(set(mounts.get(prefix + vol, [])))
    if sorted(users) != sorted({("vault", True), (agent, False)}):
        wrong.append(f"{vol}: " + (", ".join(f"{s} {'rw' if w else 'ro'}" for s, w in users) or "unused"))
report(not wrong, "AppRole credential volumes: each mounted by vault and read-only by its own agent only"
       + (f"; WRONG: {'; '.join(wrong)}" if wrong else ""))

leaks = sorted(f"{svc}: {name}" for svc, names in env_names.items() for name in CONTAINER_SECRETS if name in names)
report(bool(env_names) and not leaks,
       f"no secret in the environment compose gives the {len(env_names)} containers (docker inspect; "
       f"{len(CONTAINER_SECRETS)} names checked, VAULT_TOKEN included)"
       + (f"; FOUND: {', '.join(leaks)}" if leaks else ""))

# .env: names only. A line is reported by its name; its value is never printed.
LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
found_names, hand_set = [], []
try:
    with open(".env", encoding="utf-8") as f:
        for line in f:
            m = LINE.match(line)
            if not m:
                continue
            if m.group(1) in ENV_FILE_SECRETS:
                found_names.append(m.group(1))
            elif m.group(1) in HAND_SECRETS and m.group(2).strip().strip("\"'"):
                hand_set.append(m.group(1))
    env_read = True
except OSError:
    env_read = False
report(env_read and not found_names and not hand_set,
       ".env holds no secret: none of " + ", ".join(ENV_FILE_SECRETS) + "; "
       + " and ".join(HAND_SECRETS) + " without a value"
       + (f"; FOUND: {', '.join(sorted(set(found_names + hand_set)))} (run make: it moves them into Vault)"
          if found_names or hand_set else "") + ("" if env_read else "; .env missing"))

# The app processes (PID 1 after with-secrets) have their secrets: names and set / not set.
probe = """import sys
env = dict(kv.split(b"=", 1) for kv in open("/proc/1/environ", "rb").read().split(b"\\0") if b"=" in kv)
for name in sys.argv[1:]:
    v = env.get(name.encode())
    print(name, "unset" if v is None else "set" if v else "empty")
"""
for service, (required, optional) in PROCESS_ENV.items():
    rc, out, err = run(["docker", "compose", "exec", "-T", service, "python", "-c", probe, *required, *optional])
    state = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
    bad = [n for n in required if state.get(n) != "set"] + [n for n in optional if state.get(n) not in ("set", "empty")]
    report(rc == 0 and not bad,
           f"{service} process has {', '.join(required)} set and {', '.join(optional)} defined (presence only)"
           + (f"; NOT set: {', '.join(bad)}" if bad else "") + ("" if rc == 0 else f"; {why(err)}"))

# --- Keys file, host port, proxy ------------------------------------------------------------
rc, out, err = run(["git", "check-ignore", "-v", KEYS])
rule = out.split("\t")[0].strip() if rc == 0 else ""
tracked_keys = run(["git", "ls-files", "--error-unmatch", KEYS])[0] == 0
rc_t, tracked, _ = run(["git", "ls-files", "scripts/*.local*"])
try:
    mode = f"{os.stat(KEYS).st_mode & 0o777:o}"
except OSError:
    mode = "(file missing)"
report(bool(rule) and not tracked_keys and rc_t == 0 and not tracked.strip() and mode == "600",
       f"{KEYS}: Git-ignored ({rule or 'NOT ignored'}), "
       + ("TRACKED" if tracked_keys else "not tracked") + f", mode {mode}; "
       + (f"tracked: {' '.join(tracked.split())}" if tracked.strip() else "no scripts/*.local* file tracked"))

rc, cid, _ = run(["docker", "compose", "ps", "-q", "vault"])
rc, out, err = run(["docker", "inspect", cid.strip()]) if cid.strip() else (1, "", "no container")
info = (as_json(out) or [{}])[0] if rc == 0 else {}
bindings = (info.get("HostConfig") or {}).get("PortBindings") or {}
ports = (info.get("NetworkSettings") or {}).get("Ports") or {}
published = sorted(port for port, hosts in ports.items() if hosts)
report(rc == 0 and not bindings and not published,
       "vault publishes no host port" + (f" ({', '.join(sorted(ports))} on the Docker network only)" if ports else "")
       + (f"; PUBLISHED: {', '.join(published or sorted(bindings))}" if published or bindings else "")
       + ("" if rc == 0 else f"; docker inspect: {why(err)}"))
hits = []
for directory, _, files in os.walk("infra/proxy/templates"):
    for name in sorted(files):
        path = os.path.join(directory, name)
        with open(path, encoding="utf-8", errors="replace") as f:
            hits += [f"{path}:{n}" for n, line in enumerate(f, 1) if re.search(r"\bvault:8200\b|//vault\b", line)]
report(not hits, "no proxy route to vault: no file in infra/proxy/templates points at vault:8200"
       + (f" ({', '.join(hits)})" if hits else ""))

if failures:
    print(f"vault-check: {failures} checks failed")
    sys.exit(1)
print("vault-check: all checks passed")
PY
