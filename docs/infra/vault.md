# ft\_transcendence — Vault

Nov 19, 2026 · @byul-byul

HashiCorp Vault for module M13 (Major, buffer): "Manage secrets in Vault (API keys, credentials, environment variables), encrypted and isolated". INF-12 runs Vault in server mode, initializes and unseals it from `make`, and prepares the paths, policies and AppRole logins of the api and the worker. Nothing reads Vault yet: INF-13 moves the secrets from `.env` into it and decides how the services get them.

## TL;DR

- **Server mode, not dev mode:** `vault server -config=/vault/config/vault.hcl`, file storage on the volume `vault-data`, Shamir seal with 3 key shares and threshold 2. Vault starts sealed after every start of its container.
- **`make` does the rest:** it starts `vault` alone, runs `scripts/vault-init.sh` (init on the first run, unseal after every start, configuration applied idempotently), then starts the rest of the stack. One line of output when there is nothing to do.
- **Keys:** the key shares and the root token go to `scripts/vault-keys.local` (mode 600, Git-ignored), never to Git, the output or a command line. All three shares in one file on the machine that runs Vault is a development and defense trade-off (see The keys file).
- **Isolation:** KV v2 at `secret/`, AppRole with the roles `api` and `worker`. Policy `api` reads `secret/data/api/*` only, policy `worker` reads `secret/data/worker/*` only.
- **Audit:** the file audit device writes every request and response to stdout, so the audit log is the `vault` container log; tokens and secrets in it are HMACs.
- **Not reachable from outside:** no host port, no proxy route, no UI; only containers on the Docker network reach `vault:8200`.
- **Check:** `make vault-check`, also in CI.

## What runs

| Item | Value |
| --- | --- |
| Image | `hashicorp/vault:2.2.2@sha256:dfa48c2fa2b0099ccb47681ec5c4804bf5aec9d6879ecfee07ad4b92a5427ad6`, the latest stable release on 2026-11-19; the multi-arch index lists linux/amd64, linux/arm64 and linux/386. `make images-check` covers it (20 images) |
| Command | `vault server -config=/vault/config/vault.hcl`, written out in full: the image's default command is dev mode (`server -dev`), and its entrypoint turns a bare `server` into one with `-dev-*` flags that reads every file in `/vault/config` |
| Configuration | `infra/vault/vault.hcl`, mounted read-only: `storage "file"` at `/vault/file` (volume `vault-data`); `listener "tcp"` on `0.0.0.0:8200` with `tls_disable` (plain HTTP inside the Docker network only); `api_addr = "http://vault:8200"`; `ui = false`; `log_format = "json"`; mlock on (no `disable_mlock`) |
| User | `vault` (uid 100), the image's own user; never root |
| Memory | `cap_add: IPC_LOCK` and `ulimits: memlock: -1`, see mlock below. About 130 MiB in use, idle (`docker stats`, Docker Desktop on Apple Silicon, 2026-11-19) |
| Health check | `vault status`: exit 0 unsealed, 2 sealed, 1 no answer. 0 and 2 pass: a sealed Vault is a running server, and `make` must be able to wait for it before it unseals it. Unsealed and configured is what `make vault-check` checks |
| Ports | none on the host; 8200 on the Docker network |
| Logs | json-file, `10m` × 3 (`x-logging`, as every service): Vault's server log and the audit log, both JSON |
| Restart | `unless-stopped`; the container comes back sealed |

The `vault` service has no `depends_on`, and nothing depends on it yet.

## Start order

`make` is `env` + `up`, and `up` needs `env`, `certs` and `vault-init` first:

1. `docker compose up -d --wait --wait-timeout 120 vault`: the vault service alone, until its health check passes (sealed counts).
2. `scripts/vault-init.sh` (below).
3. `docker compose up -d --build --wait --wait-timeout 300`: the rest of the stack; `vault` is already running and is left as it is.

So once INF-13 makes the api and the worker read from Vault, it is already unsealed when they start.

## scripts/vault-init.sh

The script brings Vault to "unsealed and configured", whatever state it finds it in, and can run any number of times. It talks to Vault only through `docker compose exec -T vault vault ...` (the container sets `VAULT_ADDR=http://127.0.0.1:8200`) and parses Vault's JSON answers with python3 (no jq: neither the Macs nor the CI runner are sure to have it).

| State it finds | What it does | Output |
| --- | --- | --- |
| 1. Not initialized, no keys file (first `make`) | `vault operator init -key-shares=3 -key-threshold=2 -format=json`, the answer written straight into `scripts/vault-keys.local` (mode 600); unseals with 2 key shares; writes the configuration | `vault-init: initialized (3 key shares, threshold 2); key shares and root token in scripts/vault-keys.local (mode 600, Git-ignored)`<br>`vault-init: unsealed`<br>`vault-init: configuration written: audit device file (stdout), KV v2 at secret/, AppRole, policy api, policy worker, role api, role worker` |
| 2. Sealed, keys file present (after any restart of the container) | resets the unseal progress, sends 2 key shares, then as in 3 | `vault-init: unsealed (2 key shares from scripts/vault-keys.local)`<br>`vault-init: configuration up to date` |
| 3. Unsealed (every other `make`) | reads the configuration back and writes only what differs from the decided one | `vault-init: Vault unsealed, configuration up to date` |
| 4. Initialized, keys file missing | stops `make` with an error: without the key shares Vault cannot be unsealed, without the root token not configured; says how to put the file back or start over | the message below |
| 5. Keys file present, Vault not initialized (a new `vault-data` volume) | moves the file to `scripts/vault-keys.local.stale-<UTC time>` (Git-ignored too), then as in 1 | `vault-init: scripts/vault-keys.local belonged to a Vault that no longer exists; moved to scripts/vault-keys.local.stale-<UTC time>`, then the three lines of 1 |

The message of state 4:

```text
vault-init: Vault is initialized, but scripts/vault-keys.local is missing; without its key shares and
  root token Vault can be neither unsealed nor configured.
  If the file was moved or renamed, put it back as scripts/vault-keys.local and run make again.
  To start over with an empty Vault (everything stored in it is lost):
    docker compose rm --stop --force vault
    docker volume rm wozu_vault-data
    make
  See "Reset" in docs/infra/vault.md.
```

Other problems stop `make` the same way, with the reason: key shares or a root token that this Vault refuses (the keys file belongs to another Vault; the message adds the reset commands), `secret/` mounted as something other than KV version 2, `approle/` taken by another auth method, a Vault that does not answer.

**How the secrets travel.** The key shares reach Vault on stdin (`vault write sys/unseal -`, one `{"key": …}` per share), the root token in the environment variable `VAULT_TOKEN` of `docker compose exec` (`-e VAULT_TOKEN` without a value takes it from the script's environment). Nothing secret is printed, put on a command line (where `ps` shows it) or passed through make; the init answer goes from Vault's stdout straight into the file.

**Idempotent configuration.** Every run reads back the audit devices, the secrets engines, the auth methods, the policies and the roles, and writes only what differs from the decided state. A policy edited in `infra/vault/policies/` reaches Vault with the next `make` (or `./scripts/vault-init.sh`); a role or policy changed by hand in Vault is set back.

## The keys file

`scripts/vault-keys.local` holds Vault's answer to `vault operator init`: the 3 unseal key shares (base64 and hex), the share count and threshold, and the root token. `.gitignore` has `scripts/*.local` and `scripts/*.local.*` (the stale copies). `make vault-check` fails when the file is not ignored, is tracked, or has a mode other than 600.

**A trade-off for development and the defense.** Shamir's secret sharing splits the key that unlocks the storage into 3 shares; any 2 rebuild it, one alone tells nothing. Its point is that no single person can unseal Vault. Here all three shares and the root token sit in one file next to Vault, so whoever can read that file controls Vault, and the split protects nothing against that person. What it buys: `make` works from a fresh clone with no human step, as the subject's one-command start requires, and the demo still shows the real mechanics: server mode, sealed after every restart, unsealed by a threshold of shares, root token and shares never in Git. In production the shares go to different people (`vault operator init -pgp-keys=…` encrypts each one for its holder) or Vault unseals itself through a cloud KMS or an HSM (auto-unseal), and the root token is revoked once the setup is done and generated again only when needed (`vault operator generate-root`, with a quorum of share holders). Here the script keeps the root token to re-apply the configuration on every `make`.

**Lost or moved file.** Without the file, an initialized Vault cannot be unsealed after its next restart, and its data is lost for good; putting the file back is the only way (state 4). `make fclean` deletes the volume and moves the file aside to a `.stale-*` name, as state 5 does. A `.stale-*` file belongs to a Vault that no longer exists and can be deleted by hand.

## Secrets engine, AppRole, policies

**KV version 2 at `secret/`.** A versioned key-value store. Its API paths have a part the `vault kv` commands hide: `vault kv get secret/api/db` reads `secret/data/api/db`, and `secret/metadata/api/db` holds the versions and metadata (list, delete for good). Policies are written against the API paths, so they name `secret/data/…`.

| Policy (file) | Grants | Everything else is refused (403) |
| --- | --- | --- |
| `api` (`infra/vault/policies/api.hcl`) | `read` on `secret/data/api/*` | no `list` (nothing under `secret/metadata/`), no write or delete, no other service's path, nothing under `sys/` |
| `worker` (`infra/vault/policies/worker.hcl`) | `read` on `secret/data/worker/*` | the same |

Vault refuses whatever no policy grants. Every token also carries the built-in `default` policy, which lets it look up, renew and revoke itself and nothing under `secret/`.

**AppRole** is Vault's login for machines: a role has a role-id (like a user name) and secret-ids (like passwords); `auth/approle/login` with both returns a token with the role's policies.

| Role | Token policies | `token_ttl` | `token_max_ttl` | `secret_id_ttl` | `secret_id_num_uses` |
| --- | --- | --- | --- | --- | --- |
| `api` | `api` (+ `default`) | 1h | 4h | 0 (no expiry) | 0 (no limit) |
| `worker` | `worker` (+ `default`) | 1h | 4h | 0 (no expiry) | 0 (no limit) |

**A trade-off too.** A token lives one hour and can be renewed until four hours after the login; then the service logs in again. The role-id and the secret-id never expire and can be used any number of times, so a service can restart or log in again at any time without anyone issuing a new secret-id. The cost: a leaked role-id and secret-id pair works until someone destroys that secret-id (`auth/approle/role/<role>/secret-id-accessor/destroy`). Production setups give secret-ids a short TTL or a single use, hand them out response-wrapped by a trusted deployer, or bind them to the service's address (`secret_id_bound_cidrs`). How the role-id and the secret-id reach the api and the worker is INF-13's decision; no secret-id is issued for them yet.

## Audit log

`vault audit enable file file_path=stdout`: the audit device `file/` writes one JSON line for every request and every response to Vault's stdout, so the audit log is the `vault` container log (`docker compose logs vault`), next to Vault's own server log (JSON as well, `log_format`). The script enables it before anything else, so the rest of the setup is audited too.

- **HMAC, not clear text.** Tokens, accessors, role-ids, secret-ids and secret values appear only as `hmac-sha256:…`, with a salt of this audit device. A token's requests are found by asking Vault for its HMAC (`sys/audit-hash/file`, the token sent on stdin, as `make vault-check` does).
- **What a line shows:** the time, the path and operation, the token's policies, a refusal (`"error": "permission denied"`, the 403), the client's address (a container IP of the Docker network; `127.0.0.1` for the CLI in the vault container).
- **No personal data:** Vault holds service credentials, no user data.
- **Retention** as for every container log: rotation `10m` × 3, and `make logs-reset` at least weekly for the 30 days at most (Logs and retention in [infrastructure.md](infrastructure.md)). `make logs-reset` recreates the vault container, which starts sealed, so it runs `scripts/vault-init.sh` afterwards.
- **No request without an audit record.** Once an audit device is enabled, Vault refuses a request it cannot write to at least one of them.

## mlock

Vault locks its memory at start (`mlockall`), so that keys and secrets in memory are never written to swap, and with mlock on it stops when that fails (`Failed to lock memory: cannot allocate memory`). The decision: mlock stays on, no `disable_mlock`.

- **IPC_LOCK does not reach Vault.** Since Vault 2.0.2 the binary in the image no longer carries the `cap_ipc_lock` file capability (changelog: "Remove `cap_ipc_lock` capability on `vault` at build time … Operators should set `disable_mlock = true`"). Vault runs as uid 100, not root, so `cap_add: IPC_LOCK` (kept, as decided) never reaches its process: its effective capabilities are empty (`CapEff: 0000000000000000`).
- **The memlock limit does.** A process without that capability may still lock memory up to its `RLIMIT_MEMLOCK`. Compose sets `ulimits: memlock: -1` (unlimited) on `vault`, so the lock succeeds. Checked on 2026-11-19: with the limit at 8 MiB, a common Linux default, Vault stops at start with the error above; unlimited, it runs. Docker Desktop already defaults to unlimited; the ubuntu CI runner is covered by `make vault-check` in the `stack` job.
- **Rootless Docker** (not tested): a container cannot get a higher memlock limit than the user who runs Docker, so Vault would not start. There, `disable_mlock = true` in `infra/vault/vault.hcl`, with swap off on the host, is upstream's advice; it is not the decided setting.
- **`VmLck`** in `/proc/<pid>/status` counts the whole locked address space (about 1.6 GB, mostly reserved and never touched); the memory Vault really uses is the 130 MiB of `docker stats`. `make vault-check` requires `VmLck` above 0.

## Not reachable from outside

- **No host port:** `vault` has no `ports:`. `make vault-check` reads the container's port bindings and fails on any. `make https-check` also checks that only the proxy publishes host ports, for the compose project `wozu`.
- **No proxy route:** no template in `infra/proxy/templates/` points at `vault:8200`, and `make vault-check` fails when one does. A request to `https://localhost/vault/…` ends in the frontend's SPA fallback (`index.html`), never at Vault, so the proxy needs no 404 rule for it. The proxy's 404 rules are for paths an upstream does serve (the API's `/_internal`, `/metrics`).
- **No UI:** `ui = false`.
- **Inside the Docker network** any container can connect to `vault:8200`. Without a token only Vault's unauthenticated endpoints answer: status ones such as health and seal status, and ones that take other credentials instead (unseal needs key shares, the AppRole login a role-id and a secret-id). Everything else needs a token, and a token can do what its policies allow, no more.

## Sealed after every restart

A sealed Vault keeps its storage encrypted and refuses everything except status and unseal requests. Its memory is gone when the process stops, so it starts sealed every time: after `docker compose restart vault`, `make down` and `make`, a restart of Docker Desktop or the laptop (`restart: unless-stopped` brings the container back, sealed), and `make logs-reset`. `make` unseals it (state 2); `make logs-reset` does so itself. Today nothing reads Vault, so a sealed Vault breaks nothing; from INF-13 on, `make` after any restart is what brings the api's secrets back.

## Check: make vault-check

`infra/vault/smoke-test.sh` runs against the running stack, through `docker compose exec` (no host port), with the root token from the keys file, which it never prints. One `ok` or `FAIL` line per check, exit 1 when one failed. The isolation part uses throwaway values and one-use secret-ids (`num_uses=1`, `ttl=300`) and removes everything again, also when a check fails or the run is interrupted. Output on the stack of 2026-11-19:

```text
vault-check: Vault inside the vault container (no host port), root token from scripts/vault-keys.local
  ok    Vault 2.2.2: initialized, unsealed; shamir seal, 3 key shares, threshold 2
  ok    root token from scripts/vault-keys.local accepted
  ok    server mode: storage file, process "vault server -config=/vault/config/vault.hcl" (no -dev), UI off
  ok    runs as uid 100 (not root); mlock on, memory locked (VmLck above 0)
  ok    secrets engine at secret/: kv version 2
  ok    auth method at approle/: approle
  ok    role api: token policy api, token TTL 1h, max 4h; secret-ids without TTL or use limit
  ok    role worker: token policy worker, token TTL 1h, max 4h; secret-ids without TTL or use limit
  ok    policy api in Vault = infra/vault/policies/api.hcl: read on secret/data/api/*
  ok    policy worker in Vault = infra/vault/policies/worker.hcl: read on secret/data/worker/*
  ok    audit device file/: file to stdout (the vault container log)
  ok    root token writes a random throwaway value to secret/data/{api,worker}/vault-check
  ok    api: AppRole login with its role-id and a one-use secret-id; token policies api, default, TTL 3600 s
  ok    worker: AppRole login with its role-id and a one-use secret-id; token policies default, worker, TTL 3600 s
  ok    api token reads its own secret/data/api/vault-check
  ok    api token gets 403 reading secret/data/worker/vault-check
  ok    api token gets 403 writing its own secret/data/api/vault-check
  ok    worker token reads its own secret/data/worker/vault-check
  ok    worker token gets 403 reading secret/data/api/vault-check
  ok    worker token gets 403 writing its own secret/data/worker/vault-check
  ok    audit log: api token's requests (read own; read other, write own: permission denied), token as HMAC
  ok    audit log: worker token's requests (read own; read other, write own: permission denied), token as HMAC
  ok    audit log: none of this run's 13 credentials and values in clear (root and role tokens, accessors, role-ids, secret-ids, values)
  ok    whole vault log: no token in clear (no "hvs.")
  ok    clean-up: secret/data/{api,worker}/vault-check deleted with their metadata
  ok    clean-up: both role tokens revoked (a lookup with them gets 403)
  ok    clean-up: both one-use secret-ids gone (used up by the login, then destroyed)
  ok    scripts/vault-keys.local: Git-ignored (.gitignore:5:scripts/*.local), not tracked, mode 600; no scripts/*.local* file tracked
  ok    vault publishes no host port (8200/tcp on the Docker network only)
  ok    no proxy route to vault: no file in infra/proxy/templates points at vault:8200
vault-check: all checks passed
```

**To see it fail.** Two changes `make vault-check` must catch, each with its undo; run from the repository root against the running stack (checked on 2026-11-19).

1. **A policy that reaches too far** (the live change for the defense). In `infra/vault/policies/api.hcl`, line 4 `path "secret/data/api/*" {` becomes `path "secret/data/*" {`. Then:

   ```bash
   ./scripts/vault-init.sh   # vault-init: configuration written: policy api
   make vault-check          # fails with the lines below
   ```

   ```text
     ok    policy api in Vault = infra/vault/policies/api.hcl: read on secret/data/*
     FAIL  api token gets 403 reading secret/data/worker/vault-check: ALLOWED, policy api reaches beyond secret/data/api/*
     FAIL  audit log: api token's requests (read own; read other, write own: permission denied), token as HMAC; missing: denied read
   vault-check: 2 checks failed
   ```

   The policy line stays `ok`: Vault holds what the file says, and the line shows the wider rule. The isolation test is what refuses it: the api token reads the worker's value. Undo:

   ```bash
   git checkout -- infra/vault/policies/api.hcl && ./scripts/vault-init.sh && make vault-check
   ```

2. **No audit log.** The root token goes from the keys file into `VAULT_TOKEN` of this one command, never to the output:

   ```bash
   VAULT_TOKEN="$(python3 -c 'import json; print(json.load(open("scripts/vault-keys.local"))["root_token"])')" docker compose exec -T -e VAULT_TOKEN vault vault audit disable file
   make vault-check          # fails with the lines below
   ```

   ```text
     FAIL  audit device file/: none enabled
     FAIL  audit log: api token's requests (read own; read other, write own: permission denied), token as HMAC; no HMAC from sys/audit-hash/file
     FAIL  audit log: worker token's requests (read own; read other, write own: permission denied), token as HMAC; no HMAC from sys/audit-hash/file
   vault-check: 3 checks failed
   ```

   Undo: `./scripts/vault-init.sh` (or `make`) enables it again (`vault-init: configuration written: audit device file (stdout)`).

## Reset

To throw away Vault and everything stored in it (today nothing but its own configuration):

```bash
docker compose rm --stop --force vault
docker volume rm wozu_vault-data
make
```

`make` then finds a keys file but no initialized Vault: it moves the file to `scripts/vault-keys.local.stale-<UTC time>` and initializes a new Vault (states 5 and 1). `make fclean` does the same as part of removing the whole stack.

## For INF-13

- The service secrets go to `secret/api/<name>` and `secret/worker/<name>`, written with the root token from a script, never with values on a command line.
- Delivery to the services is open, a question to Khalil (Tech Lead) in the INF-12 PR: either the api and the worker log in with AppRole at start (a Vault client in the backend code, token renewal included), or a Vault Agent next to each of them logs in with the role-id and secret-id and renders the secrets into an env file on a `tmpfs` volume that the service reads at start, with no change to the backend code. byul-byul (PO) recommends Vault Agent.
- The role-id and the secret-id are then the only Vault access the services keep outside Vault, as the M13 checklist asks.
- Once a service reads Vault at start, it must wait for an unsealed Vault: `make` already unseals it before the rest of the stack, but the health check counts a sealed Vault as healthy, so `depends_on` alone does not wait for the unseal.

## Files

| File | What |
| --- | --- |
| `docker-compose.yml` | service `vault`, volume `vault-data` |
| `infra/vault/vault.hcl` | server configuration |
| `infra/vault/policies/api.hcl`, `worker.hcl` | the two policies |
| `scripts/vault-init.sh` | init, unseal, configuration (`--retire-keys`: only moves the keys file aside, for `make fclean`) |
| `infra/vault/smoke-test.sh` | `make vault-check` |
| `Makefile` | `vault-init` (part of `up`), `vault-check`; `logs-reset` unseals again; `fclean` moves the keys file aside |
| `.gitignore` | `scripts/*.local`, `scripts/*.local.*` |
| `.github/workflows/ci.yml` | `make vault-check` in the `stack` job, right after `make` |
