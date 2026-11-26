# ft\_transcendence — Vault

Nov 19, 2026 (INF-12), Nov 25, 2026 (INF-13) · @byul-byul

HashiCorp Vault for module M13 (Major, buffer): "Manage secrets in Vault (API keys, credentials, environment variables), encrypted and isolated". INF-12 runs Vault in server mode, initializes and unseals it from `make`, and sets up the paths, policies and AppRole logins. INF-13 moves every service secret from `.env` into Vault. The services get them from three Vault Agent sidecars, which render them into in-memory (tmpfs) volumes. The backend code does not change.

## TL;DR

- **Server mode, not dev mode:** `vault server -config=/vault/config/vault.hcl`, with file storage on the volume `vault-data` and a Shamir seal of 3 key shares, threshold 2. Vault starts sealed after every start of its container.
- **`make` does the rest:**
  - it starts `vault` alone and runs `scripts/vault-init.sh`, which initializes Vault on the first run, unseals it after every start and applies the configuration idempotently;
  - it puts the service secrets into Vault (moved from an old `.env`, or generated) and gives each agent its AppRole credentials;
  - then it starts the rest of the stack.
- **No secret in `.env`:** it holds settings and `VAULT_ADDR` only. `OPENAI_API_KEY` and `FT_CLIENT_SECRET` are typed by hand into their empty lines; the next `make` moves them into Vault and empties the lines again.
- **Three agents, three roles:**
  - `vault-agent-api` (AppRole `api`) reads `secret/data/api/*` only;
  - `vault-agent-worker` (AppRole `worker`) reads `secret/data/worker/*` only;
  - `vault-agent-infra` (AppRole `infra`) reads `secret/data/infra/*` only, for db, MinIO, Grafana, postgres-exporter and backup.
- **Secrets in memory, one volume per service:**
  - each service that needs a secret has its own tmpfs volume;
  - its agent writes the volume, and the service alone mounts it, read-only, at `/run/vault`;
  - an env file is used where the app reads environment variables, and a `*_FILE` file where the image supports one.
- **Keys:** the key shares and the root token go to `scripts/vault-keys.local` (mode 600, Git-ignored), never to Git, the output or a command line. Nowhere else is there a root token. See Honest limits.
- **After a Docker or host restart:** Vault is sealed, and the agents and the services behind them wait. `make` unseals Vault and everything comes back by itself.
- **Check:** `make vault-check`, also in CI.

## What runs

| Item | Value |
| --- | --- |
| Image | `hashicorp/vault:2.2.2@sha256:dfa48c2fa2b0099ccb47681ec5c4804bf5aec9d6879ecfee07ad4b92a5427ad6`, the latest stable release on 2026-11-19 (linux/amd64, linux/arm64, linux/386). The server and the three agents run this same image (`x-vault-image`): no new image. `make images-check` covers it |
| Command (server) | `vault server -config=/vault/config/vault.hcl`, written out in full. The image's default command is dev mode (`server -dev`), and its entrypoint turns a bare `server` into one with `-dev-*` flags that reads every file in `/vault/config` |
| Configuration | `infra/vault/vault.hcl`, mounted read-only:<br>• `storage "file"` at `/vault/file` (volume `vault-data`)<br>• `listener "tcp"` on `0.0.0.0:8200` with `tls_disable` (plain HTTP, inside the Docker network only)<br>• `api_addr = "http://vault:8200"`, `ui = false`, `log_format = "json"`<br>• mlock on (no `disable_mlock`) |
| User | `vault` (uid 100), the image's own user, never root; the agents too (`user: "100:1000"`) |
| Memory | `cap_add: IPC_LOCK` and `ulimits: memlock: -1` (see mlock below). About 130 MiB in use when idle; each agent uses a few tens of MiB |
| Health check | `vault status`: exit 0 means unsealed, 2 sealed, 1 no answer. Both 0 and 2 pass: a sealed Vault is a running server, and `make` must be able to wait for it before it unseals it. For an agent, every file it renders must exist and be non-empty |
| Ports | none on the host; 8200 on the Docker network |
| Logs | json-file, `10m` × 3 (`x-logging`): Vault's server log and the audit log, both JSON; the agents' logs (no secret values in them) |
| Restart | `unless-stopped`; Vault comes back sealed, the agents come back waiting |

## Start order

`make` is `env` + `up`, and `up` needs `env`, `certs` and `vault-init` first:

1. `docker compose up -d --wait --wait-timeout 120 vault` starts the vault service alone and waits until its health check passes (sealed counts).
2. `scripts/vault-init.sh` runs (below). It unseals and configures Vault, writes the service secrets and the agents' AppRole credentials, and removes from `.env` the secrets it moved.
3. `docker compose up -d --build --wait --wait-timeout 300` starts the rest of the stack.
   - Each agent logs in and renders its files.
   - Each service waits for its agent (`depends_on: condition: service_healthy`) and starts through `with-secrets`, which waits for its files once more.

`depends_on` is not enforced after a Docker restart: Docker restarts the containers by their `restart` policy, in any order. That is why every service waits for its own files in `with-secrets` (see After a Docker or host restart).

## scripts/vault-init.sh

The script brings Vault to "unsealed, configured and holding every service secret", whatever state it finds Vault in, and it can run any number of times.
- It talks to Vault only through `docker compose exec -T vault ...`; the container sets `VAULT_ADDR=http://127.0.0.1:8200`.
- It parses Vault's JSON answers with python3. There is no jq, because neither the Macs nor the CI runner are sure to have it.

| State it finds | What it does | Output |
| --- | --- | --- |
| 1. Not initialized, no keys file (first `make`) | runs `vault operator init -key-shares=3 -key-threshold=2 -format=json` and writes the answer straight into `scripts/vault-keys.local` (mode 600); unseals with 2 key shares; writes the configuration, the secrets and the AppRole credentials | `vault-init: initialized (3 key shares, threshold 2); key shares and root token in scripts/vault-keys.local (mode 600, Git-ignored)`<br>`vault-init: unsealed`<br>`vault-init: generated in Vault: JWT_SECRET, INTERNAL_API_KEY, POSTGRES_PASSWORD, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, GRAFANA_ADMIN_PASSWORD`<br>`vault-init: configuration written: audit device file (stdout), KV v2 at secret/, AppRole, policy api, policy worker, policy infra, role api, role worker, role infra, 14 secret paths, AppRole credentials of vault-agent-api vault-agent-worker vault-agent-infra` |
| 2. Sealed, keys file present (after any restart of the container) | resets the unseal progress and sends 2 key shares, then continues as in 3 | `vault-init: unsealed (2 key shares from scripts/vault-keys.local)`<br>`vault-init: configuration up to date` |
| 3. Unsealed (every other `make`) | reads everything back and writes only what differs | `vault-init: Vault unsealed, configuration up to date` |
| 4. Initialized, keys file missing | stops `make` with an error: without the key shares Vault cannot be unsealed, and without the root token it cannot be configured. The message says how to put the file back or start over | the message below |
| 5. Keys file present, Vault not initialized (a new `vault-data` volume) | moves the file to `scripts/vault-keys.local.stale-<UTC time>` (Git-ignored too), then continues as in 1 | `vault-init: scripts/vault-keys.local belonged to a Vault that no longer exists; moved to scripts/vault-keys.local.stale-<UTC time>`, then the lines of 1 |

While `OPENAI_API_KEY` is empty in Vault, every run adds one line about it:

```text
vault-init: OPENAI_API_KEY is not set, video moderation needs it: put it in .env (OPENAI_API_KEY=...) and run make, which moves it into Vault
```

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

Other problems stop `make` the same way, with the reason:
- key shares or a root token that this Vault refuses: the keys file belongs to another Vault, and the message adds the reset commands;
- `secret/` mounted as something other than KV version 2;
- `approle/` taken by another auth method;
- a Vault that does not answer;
- a secret whose readback differs from what was written (`.env` is then left unchanged).

**How the secrets travel.**
- The key shares and every secret value reach Vault on stdin (`vault write sys/unseal -`, `vault write secret/data/<path> -`).
- The root token reaches it in the environment variable `VAULT_TOKEN` of `docker compose exec`: `-e VAULT_TOKEN` without a value takes it from the script's environment.
- Nothing secret is printed, put on a command line (where `ps` would show it) or passed through make.
- The values read from Vault and `.env` pass through a private temporary directory (mode 700), which is removed when the script exits.

**Idempotent configuration.** Every run reads back the audit devices, the secrets engines, the auth methods, the policies, the roles, the service secrets and the agents' credentials, and writes only what differs from the decided state.
- A policy edited in `infra/vault/policies/` reaches Vault with the next `make` (or `./scripts/vault-init.sh`).
- A role or policy changed by hand in Vault is set back.

## Bootstrap and migration of the secrets

The inventory lives in one place, `secrets_py` in `scripts/vault-init.sh`. It lists each secret by its old `.env` name, how a missing one is made, and every KV path and field it goes to. For each secret, in this order:

1. **Vault already holds it:** it is kept. If `.env` has a line for it too, the line is removed and the value in it is not used. Output: `vault-init: JWT_SECRET removed from .env: Vault already holds it (secret/api/jwt, secret/worker/jwt); the .env value was not used`.
2. **Else `.env` has a non-empty value:** it is moved into Vault. This is the migration of an existing stack: the database and MinIO volumes keep working with their passwords. Output: `vault-init: POSTGRES_PASSWORD moved from .env into Vault (secret/infra/db, …)`.
3. **Else** it is generated with `openssl rand -hex 32` (`MINIO_ROOT_USER`: 10 bytes, 20 characters, within MinIO's length limit for access keys). Output: `vault-init: generated in Vault: …`.

`OPENAI_API_KEY` and `FT_CLIENT_SECRET` are typed by hand. A non-empty value in `.env` always replaces the one in Vault (that is how a key is changed), and then the value is removed while the line `OPENAI_API_KEY=` stays, ready for the next key.

**One source, every path, read back.**
- The value is written to every path that needs it: the database password, for one, goes to `infra/db`, `api/db`, `worker/db`, `infra/postgres-exporter` and `infra/backup`.
- All paths are then read back and compared with what was written. Only when they all match is `.env` edited.
- The edit is atomic, through a temporary file and `rename`, and keeps mode 600. No copy of the old `.env` is kept.
- Every line printed names keys and paths, never a value.

**What `make` does after a change.** When a running agent's secrets or AppRole credentials change, `vault-init.sh` restarts that agent, which renders again, and then the running services it feeds (they read their secrets at start). On a fresh start nothing is running yet, so nothing is restarted.

| Secret (old `.env` name) | Made by | KV paths (field) |
| --- | --- | --- |
| `JWT_SECRET` | generated | `secret/api/jwt` (value), `secret/worker/jwt` (value) |
| `INTERNAL_API_KEY` | generated | `secret/api/internal-api-key` (value) |
| `POSTGRES_PASSWORD` | generated | `secret/infra/db` (password), `secret/api/db` (password), `secret/worker/db` (password), `secret/infra/postgres-exporter` (password), `secret/infra/backup` (pg_password) |
| `MINIO_ROOT_USER` | generated | `secret/infra/minio` (root_user), `secret/api/minio` (access_key), `secret/worker/minio` (access_key), `secret/infra/backup` (minio_root_user) |
| `MINIO_ROOT_PASSWORD` | generated | `secret/infra/minio` (root_password), `secret/api/minio` (secret_key), `secret/worker/minio` (secret_key), `secret/infra/backup` (minio_root_password) |
| `GRAFANA_ADMIN_PASSWORD` | generated | `secret/infra/grafana` (admin_password) |
| `OPENAI_API_KEY` | by hand | `secret/worker/openai` (api_key) |
| `FT_CLIENT_SECRET` | by hand | `secret/api/oauth42` (client_secret) |

**Not in Vault:**
- the SMTP settings (`SMTP_HOST`, `SMTP_PORT`, `MAIL_FROM`): Mailpit takes no password, so none of them is a secret, and they stay in `.env`;
- `FT_CLIENT_ID`: the public half of the 42 app, also in `.env`;
- the user and database names (`POSTGRES_USER`, `POSTGRES_DB`), likewise in `.env`. The api and worker agents get them from compose to build `DATABASE_URL`.

## The keys file

`scripts/vault-keys.local` holds Vault's answer to `vault operator init`: the 3 unseal key shares (base64 and hex), the share count and threshold, and the root token. `.gitignore` has `scripts/*.local` and `scripts/*.local.*` (the stale copies). `make vault-check` fails when the file is not ignored, is tracked, or has a mode other than 600.

**A trade-off for development and the defense.** Shamir's secret sharing splits the key that unlocks the storage into 3 shares: any 2 rebuild it, and one alone tells nothing. Its point is that no single person can unseal Vault. Here all three shares and the root token sit in one file next to Vault, so whoever can read that file controls Vault, and the split protects nothing against that person.

What it buys:
- `make` works from a fresh clone with no human step, as the subject's one-command start requires;
- the demo still shows the real mechanics: server mode, sealed after every restart, unsealed by a threshold of shares, root token and shares never in Git.

In production:
- the shares go to different people (`vault operator init -pgp-keys=…` encrypts each one for its holder), or Vault unseals itself through a cloud KMS or an HSM (auto-unseal);
- the root token is revoked once the setup is done and generated again only when needed (`vault operator generate-root`, with a quorum of share holders).

Here the script keeps the root token to re-apply the configuration on every `make`.

**Lost or moved file.** Without the file, an initialized Vault cannot be unsealed after its next restart, and its data is lost for good. Since INF-13 that data is every service secret, so a new Vault means new passwords that the existing database and MinIO volumes do not know. Putting the file back is the only way (state 4). Back it up next to the backups (docs/disaster-recovery.md). `make fclean` deletes the volume and moves the file aside to a `.stale-*` name, as state 5 does. A `.stale-*` file belongs to a Vault that no longer exists and can be deleted by hand.

## Secrets engine, AppRole, policies

**KV version 2 at `secret/`.** A versioned key-value store. Its API paths have a part the `vault kv` commands hide: `vault kv get secret/api/db` reads `secret/data/api/db`, and `secret/metadata/api/db` holds the versions and metadata (list, delete for good). Policies are written against the API paths, so they name `secret/data/…`. One path per consumer (the inventory above): a policy can then grant one consumer exactly its own secrets.

| Policy (file) | Grants | Everything else is refused (403) |
| --- | --- | --- |
| `api` (`infra/vault/policies/api.hcl`) | `read` on `secret/data/api/*` | no `list` (nothing under `secret/metadata/`), no write or delete, no other consumer's path, nothing under `sys/` |
| `worker` (`infra/vault/policies/worker.hcl`) | `read` on `secret/data/worker/*` | the same |
| `infra` (`infra/vault/policies/infra.hcl`, INF-13) | `read` on `secret/data/infra/*` | the same |

Vault refuses whatever no policy grants. Every token also carries the built-in `default` policy, which lets it look up, renew and revoke itself, and gives nothing under `secret/`.

**AppRole** is Vault's login for machines. A role has a role-id (like a user name) and secret-ids (like passwords); `auth/approle/login` with both returns a token with the role's policies.

| Role | Used by | Token policies | `token_ttl` | `token_max_ttl` | `secret_id_ttl` | `secret_id_num_uses` |
| --- | --- | --- | --- | --- | --- | --- |
| `api` | `vault-agent-api` | `api` (+ `default`) | 1h | 4h | 0 (no expiry) | 0 (no limit) |
| `worker` | `vault-agent-worker` | `worker` (+ `default`) | 1h | 4h | 0 (no expiry) | 0 (no limit) |
| `infra` | `vault-agent-infra` | `infra` (+ `default`) | 1h | 4h | 0 (no expiry) | 0 (no limit) |

**A trade-off too.** A token lives one hour and the agent renews it until four hours after the login; then the agent logs in again on its own. The secret-ids never expire and have no use limit, so an agent can restart or log in again at any time without anyone issuing a new one. The cost: a leaked role-id and secret-id pair keeps working until someone destroys that secret-id (`auth/approle/role/<role>/secret-id-accessor/destroy`; the next `make` then issues a new one, see below). Production setups give secret-ids a short TTL or a single use, hand them out response-wrapped by a trusted deployer, or bind them to the service's address (`secret_id_bound_cidrs`). `make vault-check` keeps using its own one-use secret-ids (`num_uses=1`, `ttl=300`).

**How each agent gets its credentials.**
- `vault-init.sh` writes each role's `role-id` and `secret-id` from inside the vault container (`docker compose exec -u 0 vault sh -c …`) into the named volume `vault-approle-<role>`, mounted in vault at `/vault/approle/<role>`. They never pass through the host or its disk.
- The files belong to uid 100, the directory has mode 500 and the files mode 400.
- Each agent mounts only its own volume, read-only, at `/vault/approle`.
- A secret-id is kept while Vault still knows it (checked with `secret-id/lookup`). When it does not (destroyed, or a new Vault), a new one is written and the agent restarted.
- Compose would need Engine 26 to mount one volume's subpath, so there are three volumes, one per role.

## Audit log

`vault audit enable file file_path=stdout`: the audit device `file/` writes one JSON line for every request and every response to Vault's stdout, so the audit log is the `vault` container log (`docker compose logs vault`), next to Vault's own server log (JSON as well, `log_format`). The script enables it before anything else, so the rest of the setup is audited too.

- **HMAC, not clear text.** Tokens, accessors, role-ids, secret-ids and secret values appear only as `hmac-sha256:…`, with a salt of this audit device. A token's requests are found by asking Vault for its HMAC (`sys/audit-hash/file`, the token sent on stdin, as `make vault-check` does).
- **What a line shows:** the time, the path and operation, the token's policies, a refusal (`"error": "permission denied"`, the 403), the client's address (a container IP of the Docker network; `127.0.0.1` for the CLI in the vault container).
- **No personal data:** Vault holds service credentials, no user data.
- **Retention** as for every container log: rotation `10m` × 3, and `make logs-reset` at least weekly for the 30 days at most (Logs and retention in [infrastructure.md](infrastructure.md)). `make logs-reset` recreates the vault container, which starts sealed, so it runs `scripts/vault-init.sh` afterwards.
- **No request without an audit record.** Once an audit device is enabled, Vault refuses a request it cannot write to at least one of them.

## Vault Agents

Three long-running sidecars from the vault image, as uid 100. Each reads its configuration from `infra/vault/agent/<name>.hcl` and its templates from `infra/vault/agent/templates/`, both mounted read-only.

| Agent | AppRole | Renders (into the volume of) | Read by |
| --- | --- | --- | --- |
| `vault-agent-api` | `api` | `env` (`secrets-api`): `JWT_SECRET`, `INTERNAL_API_KEY`, `DATABASE_URL` (password inside), `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `FT_CLIENT_SECRET`<br>`env` (`secrets-api-test`): the same without `FT_CLIENT_SECRET`, plus `TEST_DATABASE_URL` | `api`, `api-test` (`make test`) |
| `vault-agent-worker` | `worker` | `env` (`secrets-worker`): `JWT_SECRET`, `DATABASE_URL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `OPENAI_API_KEY` | `worker` |
| `vault-agent-infra` | `infra` | `postgres-password` (`secrets-db`)<br>`root-user`, `root-password` (`secrets-minio`)<br>`env` (`secrets-minio-init`): `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`<br>`admin-password` (`secrets-grafana`)<br>`password` (`secrets-postgres-exporter`)<br>`env` (`secrets-backup`): `PGPASSWORD`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | `db`, `minio`, `minio-init`, `grafana`, `postgres-exporter`, `backup` |

- **Login:** `auto_auth` with AppRole, from the two files, which are kept after reading (`remove_secret_id_file_after_reading = false`) so that a restarted agent can log in again. While Vault is sealed or unreachable, the login is retried with a backoff of 1 s to 10 s, so the agent renders within about 10 s of `make` unsealing Vault.
- **Token:** renewed and replaced by the agent. There is no sink and no listener: the token never leaves the agent process.
- **Files:**
  - env files are `NAME='value'` lines, in which a `'` inside a value is written `'\''`, so `sh` sources them unchanged;
  - `*_FILE` files hold the bare value, without a newline;
  - all files are mode 0444 inside a volume of mode 0755 that belongs to uid 100;
  - `error_on_missing_key` makes a missing field an error instead of an empty value.
- **Re-render:** the agent reads the KV secrets again every 5 minutes (its default for static secrets) and rewrites a file when the value changed. A service reads its secrets at start, so `vault-init.sh` restarts it after a change.
- **Failure:** when a template still cannot read its secret after the retries (Vault sealed again, or a policy that no longer allows the path), the agent exits (`exit_on_retry_failure`) and Docker starts it again. The start (`rm -f /tmp/rendered; exec vault agent …`) removes only the agent's private readiness marker, so the health check turns red until this run of the agent has read every one of its paths.
- **The rendered files are never deleted,** only replaced by an atomic rename. A first version emptied them at every agent start. On 2026-11-25, after a `docker compose restart` of the whole stack, that raced with MinIO: `with-secrets` saw the files, the agent removed them, and MinIO, finding no `*_FILE`, started with its default credentials `minioadmin:minioadmin`. `make vault-check` now checks that MinIO refuses them.
- **Health:** the marker `/tmp/rendered` (the agent's last template, which reads every path of the agent and holds no secret) and every file the agent renders exist and are non-empty (`test -s`).

## Rendered secrets on tmpfs

One named volume per consumer (`x-secrets-volume`: `driver: local`, `type: tmpfs`, `size=64k,uid=100,gid=1000,mode=0755`):
- `secrets-api`, `secrets-api-test` and `secrets-worker`;
- `secrets-db`, `secrets-minio`, `secrets-minio-init`, `secrets-grafana`, `secrets-postgres-exporter` and `secrets-backup`.

- **In memory only.** The files never reach a disk, and the volume is empty again once no container uses it (after `make down`, a Docker or host restart).
- **Isolated.** Each volume is mounted read-write by its agent only and read-only by its one service only, at `/run/vault`. The worker cannot see the api's file, and Grafana cannot see the database password. `make vault-check` checks the mount map of every container of the project.
- **`with-secrets`** (`infra/vault/with-secrets.sh`, mounted read-only at `/usr/local/bin/with-secrets`) is the entrypoint wrapper of every consumer:
  1. it waits until each file in `VAULT_SECRET_FILES` and `VAULT_ENV_FILE` is non-empty;
  2. it exports the env file (`set -a; . file; set +a`);
  3. it runs the image's own entrypoint or command with `exec`.

  The wait matters: MinIO with a missing `*_FILE` starts with its default credentials `minioadmin:minioadmin` (checked on 2026-11-25). After `VAULT_WAIT_SEC` (300 s) without the files it exits 1, and `restart: unless-stopped` tries again.
- **`docker compose exec`** starts a process without the entrypoint, so it does not have the secrets. Run it through the wrapper: `docker compose exec worker with-secrets python -m …`, as `make anonymise-deleted`, `make seed`, `make reset-demo`, `make mail-check` and `make https-check` do. `backup.sh` sources its env file itself, so `make backup` and `make restore` need no wrapper.

| Service | How it reads its secret | Variable (compose) |
| --- | --- | --- |
| `api`, `worker`, `api-test` | env file, exported by `with-secrets` before uvicorn, celery, pytest | `VAULT_ENV_FILE=/run/vault/env` |
| `db` | `POSTGRES_PASSWORD_FILE` (the postgres image, only on a new volume) | `POSTGRES_PASSWORD_FILE=/run/vault/postgres-password` |
| `minio` | `MINIO_ROOT_USER_FILE`, `MINIO_ROOT_PASSWORD_FILE` | `/run/vault/root-user`, `/run/vault/root-password` |
| `minio-init` | env file (`mc alias` through `MC_HOST_*`) | `VAULT_ENV_FILE=/run/vault/env` |
| `grafana` | `GF_SECURITY_ADMIN_PASSWORD__FILE` (Grafana sets it on a new `grafana-data`) | `/run/vault/admin-password` |
| `postgres-exporter` | `DATA_SOURCE_PASS_FILE` | `/run/vault/password` |
| `backup` | env file, sourced by `backup.sh` at every start (loop, `make backup`, `make restore`) | `VAULT_ENV_FILE=/run/vault/env` |

To see a secret:
- the Grafana admin password: `docker compose exec grafana cat /run/vault/admin-password`;
- the same value through Vault, with the root token (never printed):

```bash
VAULT_TOKEN="$(python3 -c 'import json; print(json.load(open("scripts/vault-keys.local"))["root_token"])')" \
  docker compose exec -T -e VAULT_TOKEN vault vault kv get -field=admin_password secret/infra/grafana
```

## After a Docker or host restart

A sealed Vault keeps its storage encrypted and refuses everything except status and unseal requests. Its memory is gone when the process stops, so it starts sealed every time:
- after `docker compose restart vault`;
- after `make down` and then `make`;
- after a restart of Docker Desktop or of the machine;
- after `make logs-reset`.

After a Docker or host restart:

1. Docker brings the containers back (`restart: unless-stopped`) in any order, with the tmpfs volumes empty.
2. Vault is sealed. The agents start and retry the login every 10 s at most; their health checks are red. (After `docker compose restart` instead, the tmpfs volumes stay mounted and keep their files, so the services start at once with the current values; only the agents wait.)
3. The services behind them wait in `with-secrets` for their files (MinIO logs `with-secrets: waiting for /run/vault/root-user from this service's Vault Agent (sealed Vault? run make)`). After 300 s they exit and Docker starts them again, so they keep waiting. Redis, Mailpit, Prometheus and the frontend start normally. The proxy serves the frontend, but `/api` answers 502 until the api is up.
4. `make` unseals Vault (state 2). The agents log in, render within about 10 s, and the waiting services start. `make`'s own `up --wait` then finds the stack healthy. Tested on 2026-11-25 by stopping every container and starting them all at once, as Docker does at boot: Vault sealed, the volumes empty, `/api` 502; then `make` (32 s), `/api` 200 and `make vault-check` green.

So after any restart, `make` (or just `./scripts/vault-init.sh`) is the step that brings the secrets back. `make logs-reset` does it itself: it recreates `vault` first, runs `scripts/vault-init.sh`, then recreates the rest.

## Honest limits

- **The unseal keys and the root token are on the same machine** as Vault, in `scripts/vault-keys.local`. Anyone who can read that file (the owner of the checkout, or root) can unseal Vault and read every secret. This is the price of a one-command start with no human step; see The keys file for what production does instead.
- **A rendered secret is readable by root on the host** (through `/var/lib/docker/volumes/…` or `docker exec`), **and inside its consumer**: the process, anyone who can `docker compose exec` into it, `/proc/1/environ` for the env-file services. Vault Agent protects the secret at rest and between services, not from someone who controls the Docker host.
- **A rendered file keeps its last value while its agent cannot render** (Vault sealed again, a policy revoked): the agent's health check and `make vault-check` turn red, but a service that restarts then still starts with that value. After a host restart the volumes are empty, so nothing starts before `make` unseals Vault.
- **Anyone who can use Docker on the host controls everything.** `docker compose exec -u 0 vault cat /vault/approle/api/secret-id` hands over an AppRole login. Docker access equals root here, as for every Docker stack.
- **The database and MinIO passwords cannot be rotated by changing them in Vault alone.** The postgres image and MinIO keep the password their volume was created with. To change one, change it in the service (`ALTER ROLE`, `mc admin user`) and in Vault, then run `make`, which restarts the agents and services. Grafana is the same: `grafana cli admin reset-admin-password`.
- **The MinIO access key ID is not secret by design:** every presigned URL the api hands to a browser carries it in `X-Amz-Credential` (and `make files-check` prints one). The secret key never leaves the server; a URL proves its signature only. Vault keeps the access key ID with the secret key because they are one credential pair.
- **The api and worker still use MinIO's root credentials** (`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` = root user and password), as before INF-13. A dedicated MinIO service account is out of this card's scope.
- **Plain HTTP inside the Docker network** (`tls_disable`): the AppRole login and the rendered secrets cross the bridge network unencrypted. No other host or container outside the project sees that network.
- **`make fclean` deletes the secrets with the Vault volume.** The generated ones are made again for the new volumes. `OPENAI_API_KEY` and `FT_CLIENT_SECRET` must be typed into `.env` again before the next `make`.

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

## Check: make vault-check

`infra/vault/smoke-test.sh` runs against the running stack, through `docker compose exec` (no host port), with the root token from the keys file, which it never prints. It prints one `ok` or `FAIL` line per check and exits 1 when one failed. The isolation part uses throwaway values and one-use secret-ids (`num_uses=1`, `ttl=300`), and removes everything again, also when a check fails or the run is interrupted. The INF-13 part:
- reads the real secrets, but only compares them and never prints one;
- reads `.env` by names only, never printing a value;
- reads the process environments by names only, printing `set` / `empty` / `unset` per name.

Output on a fresh stack, 2026-11-25:

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
  ok    role infra: token policy infra, token TTL 1h, max 4h; secret-ids without TTL or use limit
  ok    policy api in Vault = infra/vault/policies/api.hcl: read on secret/data/api/*
  ok    policy worker in Vault = infra/vault/policies/worker.hcl: read on secret/data/worker/*
  ok    policy infra in Vault = infra/vault/policies/infra.hcl: read on secret/data/infra/*
  ok    audit device file/: file to stdout (the vault container log)
  ok    root token writes a random throwaway value to secret/data/{api,worker,infra}/vault-check
  ok    api: AppRole login with its role-id and a one-use secret-id; token policies api, default, TTL 3600 s
  ok    worker: AppRole login with its role-id and a one-use secret-id; token policies default, worker, TTL 3600 s
  ok    infra: AppRole login with its role-id and a one-use secret-id; token policies default, infra, TTL 3600 s
  ok    api token reads its own secret/data/api/vault-check
  ok    api token gets 403 reading secret/data/worker/vault-check
  ok    api token gets 403 reading secret/data/infra/vault-check
  ok    api token gets 403 writing its own secret/data/api/vault-check
  ok    worker token reads its own secret/data/worker/vault-check
  ok    worker token gets 403 reading secret/data/api/vault-check
  ok    worker token gets 403 reading secret/data/infra/vault-check
  ok    worker token gets 403 writing its own secret/data/worker/vault-check
  ok    infra token reads its own secret/data/infra/vault-check
  ok    infra token gets 403 reading secret/data/api/vault-check
  ok    infra token gets 403 reading secret/data/worker/vault-check
  ok    infra token gets 403 writing its own secret/data/infra/vault-check
  ok    service secrets: the 14 KV paths of the inventory, every field set (hand-typed, still empty: secret/worker/openai)
  ok    api token reads its 5 real paths secret/api/* and gets 403 on every worker/infra path
  ok    worker token reads its 4 real paths secret/worker/* and gets 403 on every api/infra path
  ok    infra token reads its 5 real paths secret/infra/* and gets 403 on every api/worker path
  ok    audit log: api token's requests (read own; read other, write own: permission denied), token as HMAC
  ok    audit log: worker token's requests (read own; read other, write own: permission denied), token as HMAC
  ok    audit log: infra token's requests (read own; read other, write own: permission denied), token as HMAC
  ok    audit log: none of this run's 19 credentials and values in clear (root and role tokens, accessors, role-ids, secret-ids, values)
  ok    whole vault log: no token in clear (no "hvs.")
  ok    clean-up: secret/data/{api,worker,infra}/vault-check deleted with their metadata
  ok    clean-up: every role token revoked (a lookup with it gets 403)
  ok    clean-up: every one-use secret-id gone (used up by the login, then destroyed)
  ok    vault-agent-api (AppRole api): running, health healthy; rendered 2 non-empty files (api/env, api-test/env)
  ok    vault-agent-worker (AppRole worker): running, health healthy; rendered 1 non-empty file (worker/env)
  ok    vault-agent-infra (AppRole infra): running, health healthy; rendered 7 non-empty files (db/postgres-password, minio/root-user, minio/root-password, minio-init/env, grafana/admin-password, postgres-exporter/password, backup/env)
  ok    minio refuses the default credentials minioadmin:minioadmin (its root user and password come from Vault)
  ok    rendered-secret volumes: 9 tmpfs volumes, each written by its agent only and read-only by its one service only
  ok    AppRole credential volumes: each mounted by vault and read-only by its own agent only
  ok    no secret in the environment compose gives the 20 containers (docker inspect; 16 names checked, VAULT_TOKEN included)
  ok    .env holds no secret: none of JWT_SECRET, INTERNAL_API_KEY, POSTGRES_PASSWORD, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, GRAFANA_ADMIN_PASSWORD; OPENAI_API_KEY and FT_CLIENT_SECRET without a value
  ok    api process has JWT_SECRET, INTERNAL_API_KEY, DATABASE_URL, MINIO_ACCESS_KEY, MINIO_SECRET_KEY set and FT_CLIENT_SECRET defined (presence only)
  ok    worker process has JWT_SECRET, DATABASE_URL, MINIO_ACCESS_KEY, MINIO_SECRET_KEY set and OPENAI_API_KEY defined (presence only)
  ok    scripts/vault-keys.local: Git-ignored (.gitignore:5:scripts/*.local), not tracked, mode 600; no scripts/*.local* file tracked
  ok    vault publishes no host port (8200/tcp on the Docker network only)
  ok    no proxy route to vault: no file in infra/proxy/templates points at vault:8200
vault-check: all checks passed
```

**To see it fail.** Three changes `make vault-check` must catch, each with its undo. Run them from the repository root against the running stack.

1. **A secret back in `.env`** (the negative run of INF-13):

   ```bash
   echo 'JWT_SECRET=x' >> .env
   make vault-check          # fails with the line below
   ```

   ```text
   vault-check: Vault inside the vault container (no host port), root token from scripts/vault-keys.local
     ...
     FAIL  .env holds no secret: none of JWT_SECRET, INTERNAL_API_KEY, POSTGRES_PASSWORD, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, GRAFANA_ADMIN_PASSWORD; OPENAI_API_KEY and FT_CLIENT_SECRET without a value; FOUND: JWT_SECRET (run make: it moves them into Vault)
     ...
   vault-check: 1 checks failed
   ```

   Undo: `make`. Vault already holds `JWT_SECRET`, so the line is removed and the `x` is not used:

   ```text
   vault-init: JWT_SECRET removed from .env: Vault already holds it (secret/api/jwt, secret/worker/jwt); the .env value was not used
   vault-init: Vault unsealed, configuration up to date
   ```

2. **An agent that is no longer allowed to read its path** (the live change for the defense). In `infra/vault/policies/infra.hcl`, the line `path "secret/data/infra/*" {` becomes `path "secret/data/infra/nothing/*" {`. Then:

   ```bash
   ./scripts/vault-init.sh                    # vault-init: configuration written: policy infra
   docker compose restart vault-agent-infra   # renders again: 403 on every infra path
   make vault-check                           # fails with the lines below
   ```

   ```text
   vault-check: Vault inside the vault container (no host port), root token from scripts/vault-keys.local
     FAIL  infra token reads its own secret/data/infra/vault-check: * permission denied
     FAIL  infra token reads its 5 real paths secret/infra/* (NOT all) and gets 403 on every api/worker path
     FAIL  audit log: infra token's requests (read own; read other, write own: permission denied), token as HMAC; missing: read
     FAIL  vault-agent-infra (AppRole infra): running, health starting; MISSING or empty: /tmp/rendered, minio-init/env
   vault-check: 4 checks failed
   ```

   The services already running keep their secrets in memory; a restarted db, MinIO or Grafana would wait in `with-secrets`. Undo:

   ```bash
   git checkout -- infra/vault/policies/infra.hcl && ./scripts/vault-init.sh && docker compose restart vault-agent-infra && make vault-check
   ```

3. **A policy that reaches too far.** In `infra/vault/policies/api.hcl`, line 4 `path "secret/data/api/*" {` becomes `path "secret/data/*" {`. Then `./scripts/vault-init.sh` and `make vault-check`. The isolation tests then fail: the api token reads the worker's and infra's throwaway values and their real paths (`READABLE: secret/infra/db, …`). Undo: `git checkout -- infra/vault/policies/api.hcl && ./scripts/vault-init.sh`.

## Reset

To throw away Vault and everything stored in it:

```bash
docker compose rm --stop --force vault
docker volume rm wozu_vault-data
make
```

`make` then finds a keys file but no initialized Vault. It moves the file to `scripts/vault-keys.local.stale-<UTC time>` and initializes a new Vault (states 5 and 1), with **new** generated secrets. Those match no existing database or MinIO volume, so reset Vault only together with them (`make fclean`), or restore the old `vault-data` and keys file instead.

## Decisions (INF-13)

- **Vault Agent, not a Vault client in the backend.** Agreed with Khalil (Tech Lead) in #82: the backend code does not change and does not renew tokens. The services read environment variables or `*_FILE` files, as before.
- **Three agents, one per trust domain** (api, worker, infra), each with its own AppRole and policy, rather than one agent with a policy that reads everything.
- **One KV path per consumer**, with a shared value written to each path from one source. The policies stay simple prefix rules, and the INF-12 isolation tests still apply.
- **tmpfs volumes, one per consumer**, rather than one shared volume: a compose volume mount cannot select files, so isolation needs separate volumes.
- **No secret file on the host**: the AppRole credentials go from Vault into named volumes inside the vault container.

## Files

| File | What |
| --- | --- |
| `docker-compose.yml` | the services `vault`, `vault-agent-api`, `vault-agent-worker`, `vault-agent-infra`; the volumes `vault-data`, `vault-approle-*`, `secrets-*` (tmpfs); `with-secrets` and `/run/vault` on every consumer |
| `infra/vault/vault.hcl` | server configuration |
| `infra/vault/policies/api.hcl`, `worker.hcl`, `infra.hcl` | the three policies |
| `infra/vault/agent/api.hcl`, `worker.hcl`, `infra.hcl` | agent configurations (AppRole login, templates) |
| `infra/vault/agent/templates/*.ctmpl` | the env-file templates (api, api-test, worker, minio-init, backup) |
| `infra/vault/with-secrets.sh` | the wait-and-export entrypoint wrapper |
| `scripts/vault-init.sh` | init, unseal, configuration, secrets bootstrap and migration, AppRole credentials, agent restarts (`--retire-keys`: only moves the keys file aside, for `make fclean`) |
| `scripts/init-env.sh` | creates `.env` from `.env.example`; no secret generated any more |
| `infra/vault/smoke-test.sh` | `make vault-check` |
| `Makefile` | `vault-init` (part of `up`, `test`, `restore`), `vault-check`; `logs-reset` unseals Vault before the rest; `fclean` moves the keys file aside |
| `.gitignore` | `scripts/*.local`, `scripts/*.local.*` |
| `.github/workflows/ci.yml` | `make vault-check` in the `stack` job, right after `make` |
