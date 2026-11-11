# ft\_transcendence — Infrastructure

Oct 27, 2026 · updated Nov 4, 2026 · @byul-byul

## TL;DR

Infra owns four mandatory items and five module points. The reference already has a working compose stack (Caddy, API, Celery worker, Postgres + PostGIS, Redis, MinIO); what is missing is the frontend container, HTTPS for file storage, a mail catcher and everything for the modules.

- **Mandatory:** one command starts everything; every browser connection is HTTPS; `.env` stays out of Git with a complete `.env.example`; the evaluator can sign up without a paid email service.
- **Modules:** Prometheus + Grafana (Major, 2, core); WAF / ModSecurity + Vault (Major, 2, buffer); health check, status page and backups (Minor, 1, buffer).
- **Front proxy decided (2026-11-04, INF-01):** nginx + ModSecurity v3 + OWASP Core Rule Set is the only front door instead of Caddy. Configuration: [infra/proxy/](../../infra/proxy/README.md).
- **One origin for everything** (`https://localhost` at the defense): frontend at `/`, API at `/api`, WebSockets at `/ws`, files at `/files`, Grafana at `/grafana`, Mailpit at `/mail`. One certificate warning, no CORS, no mixed content.

## Front proxy (decided 2026-11-04)

nginx + ModSecurity v3 + OWASP Core Rule Set (CRS), image `owasp/modsecurity-crs:nginx-alpine`, decided in card INF-01 (byul-byul) and logged in the decisions log of the overview. Caddy from the reference is not used. Reason: the WAF module (M13) needs ModSecurity, and switching proxies late costs more than choosing now. INF-03 implements the routes below as nginx `location` blocks; INF-11 tunes CRS in blocking mode.

## Services

Only the proxy publishes ports to the host; everything else stays on the internal Docker network. Pin every image tag (the reference uses `minio/minio:latest`). All services are in the root `docker-compose.yml` (compose project `wozu`) since INF-02; INF-07 pins the remaining images by digest and adds the full health checks.

| Service | Image | Purpose | Published | Status |
| --- | --- | --- | --- | --- |
| `proxy` | `owasp/modsecurity-crs:4.30.0-nginx-alpine-202610180210`, by digest | TLS, single origin, routing, WAF | 443 (80 → redirect); host ports set by `HTTPS_PORT` / `HTTP_PORT` | In compose (INF-02) |
| `frontend` | Built from `frontend/` (FE-01 Dockerfile, stage `preview`: Node build → `nginx:1.28-alpine`); site config `infra/frontend/default.conf` mounted for the SPA fallback | React app | no | In compose (INF-02) |
| `api` | Built from `backend/` (Python 3.11 slim, multi-stage, no test deps) | FastAPI, runs migrations on start; waits for `db` and `redis` to be healthy | no | In compose, `/api/health` health check (Python `urllib`; the image has no curl) |
| `worker` | Same image as `api`, command `celery -A app.worker.celery_app worker -B` | Video moderation + beat for stuck videos | no | In compose behind the `worker` profile (off by default) until BE-29 adds the Celery app |
| `db` | `imresamu/postgis:15-3.4`, by digest (PostgreSQL 15 + PostGIS 3.4 from the docker-postgis sources, amd64 + arm64; every `postgis/postgis` tag is amd64 only, so Apple Silicon would run it emulated) | PostgreSQL + PostGIS; app database `POSTGRES_DB` and test database `POSTGRES_TEST_DB` | no | In compose, `pg_isready` health check |
| `redis` | `redis:7-alpine` | Pub/sub, queues, rate limits, Celery broker | no | In compose, `redis-cli ping` health check |
| `minio` | `pgsty/minio:RELEASE.2026-08-04T00-00-00Z`, by digest (the official `minio/minio` and `minio/mc` images left Docker Hub on 2025-10-23) | Object storage for videos, avatars, logos | no (proxied at `/files`) | In compose; bucket in INF-04 |
| `minio-init` | to be chosen in INF-04 (`minio/mc` is gone) | One-shot: create bucket `files`, set policies | no | INF-04 |
| `mailpit` | `axllent/mailpit:v1.33.1` | Catches all outgoing mail, web inbox | no (proxied at `/mail`) | In compose (INF-02) |
| `prometheus` | `prom/prometheus` | Metrics scraping, alert rules | no | New (module) |
| `grafana` | `grafana/grafana` | Dashboards, provisioned from files | no (proxied at `/grafana`) | New (module) |
| exporters | `postgres-exporter`, `redis-exporter`, `cadvisor` or `node-exporter` | DB, Redis, container metrics | no | New (module) |
| `vault` | `hashicorp/vault` (server mode, file storage) | Secrets for API keys and credentials | no | Buffer module |
| `backup` | small image with `pg_dump` + `mc` + cron | Daily dumps of DB and bucket, 7-day retention | no | Buffer module |

We skip ELK: Elasticsearch is memory-hungry and risky on an evaluation laptop; Prometheus + Grafana gives the same 2 points with a lighter footprint.

## One origin over HTTPS

Everything the browser touches goes through one host and one certificate. Locally that is `https://localhost` with a self-signed certificate from `infra/proxy/scripts/gen-cert.sh`, so the evaluator accepts one warning once.

| Path | Upstream | Notes |
| --- | --- | --- |
| `/` | `frontend:80` | The frontend container does the SPA fallback to `index.html` for client routes |
| `/api/*` | `api:8000` | FastAPI includes all routers under the `/api` prefix; the proxy does not strip paths |
| `/ws`, `/ws/game` | `api:8000` | WebSocket upgrade: HTTP/1.1, `Upgrade` and `Connection` headers, long read timeout |
| `/files/*` | `minio:9000` | Bucket `files`; Host header passed through unchanged so presigned signatures match; 60 MB body limit |
| `/grafana/*` | `grafana:3000` | `GF_SERVER_ROOT_URL=https://localhost/grafana/`, `serve_from_sub_path=true`, login required |
| `/mail/*` | `mailpit:8025` | `MP_WEBROOT=/mail/` |
| `/_internal/*`, `/metrics` | blocked | Prometheus scrapes them inside the Docker network only |
| `http://` any | redirect to `https://` |  |

The table translates one-to-one to the `location` blocks in `infra/proxy/templates/conf.d/default.conf.template`. ModSecurity covers all of them and runs in `DetectionOnly` until INF-11 switches it to blocking. The image runs unprivileged and listens on 8080 and 8443 inside the container, so compose publishes `443:8443` and `80:8080`. `HTTPS_PORT` and `HTTP_PORT` in `.env` change the host side; the redirect then carries the HTTPS port (`http://localhost:8080/` → `https://localhost:8443/`). `infra/proxy/README.md` lists which files are ours and which come from the image.

## File storage over HTTPS

Recommendation: serve the bucket on the same origin at `/files/*` and presign URLs for `https://<domain>`. It keeps the reference's presigned-upload design, needs no second certificate and no CORS.

| Option | How | Pros | Cons |
| --- | --- | --- | --- |
| **A. Same origin, bucket path (recommended)** | Bucket named `files`; proxy routes `/files/*` → `minio:9000` with the Host header unchanged; API presigns with `MINIO_EXTERNAL_ENDPOINT=https://<domain>` | One cert, no CORS, minimal backend change | Bucket name is part of the public URL |
| B. Separate port, e.g. `https://<domain>:9443` | Second TLS listener → MinIO | Clean separation | Second self-signed warning the evaluator must also accept, or uploads fail silently; CORS needed |
| C. Upload through the API | Browser posts multipart to `/api/media/...`; API streams to MinIO | Server sees the bytes (real size, type, duration checks) | 50 MB requests through the API, more backend work |

**Required with option A:**

- The worker must download videos with the internal MinIO client (`minio:9000`), not through the external presigned URL: inside a container `https://localhost` is the container itself. The reference downloads via the external URL (`moderation_task.py`), so this is a backend card (BE-29).
- `minio-init` creates the bucket and keeps it private; all access goes through presigned URLs (GET 5 min, PUT 15 min).
- On `confirm`, the API calls `stat_object` to check the file exists and its real size.
- Avatars need a stable read path: either short-lived presigned GET URLs returned in API responses, or a public-read prefix `files/avatars/*` (no secrets in avatars). byul-byul picks one with Khalil (Tech Lead); BE-08 returns `avatar_url` and `logo_url`.

## Email without a paid service

Add Mailpit and send mail over plain SMTP from the API; the evaluator opens `https://localhost/mail` to click the verification link. The reference only speaks the Brevo HTTP API and prints the link to the log when no key is set.

- `mailpit` container: SMTP on `mailpit:1025` (internal), web inbox on `8025`, proxied at `/mail` with `MP_WEBROOT=/mail/`.
- API env: `SMTP_HOST=mailpit`, `SMTP_PORT=1025`, `MAIL_FROM=no-reply@wozu.local`; keep Brevo as an optional sender when `BREVO_API_KEY` is set.
- Email links use `FRONTEND_BASE_URL` (`https://localhost`): `/verify-email?token=…`, `/reset-password?token=…`.
- Mention Mailpit in the README "Instructions" so the evaluator knows where verification emails land.

## One-command start and secrets

`make` must take a fresh clone to a running site: it creates `.env` from `.env.example` with random secrets when missing, then builds and starts the stack. The only value a human must add is `OPENAI_API_KEY` (moderation module).

| Target | What it does |
| --- | --- |
| `make` (`all`) | `env` + `up` |
| `make env` | `scripts/init-env.sh`: when `.env` is missing, copies `.env.example` and fills the empty secrets (`JWT_SECRET`, `INTERNAL_API_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`) with `openssl rand -hex 32`; prints their names, never the values; never overwrites an existing `.env` |
| `make up` | `env`, then `infra/proxy/scripts/gen-cert.sh` (the proxy exits without a certificate), then `docker compose up -d --build --wait`, which returns once `db`, `redis` and `api` are healthy |
| `make down` | stops and removes the containers, keeps volumes |
| `make logs` | last 100 lines of every service, then follows; `make logs s=api` for one service |
| `make test` | starts `db` if needed and creates the test database when it is missing (see below); backend `ruff` + `pytest` in the `api` image (dev tools installed in a throwaway container, code mounted read-only), with `DATABASE_URL` set to `TEST_DATABASE_URL` as in CI; frontend lint, format check, type check and `vitest` in the build stage of its image. Leaves `db` and `redis` running |
| `make fclean` | removes containers, volumes, the images built here and the certificate; **keeps `.env`**, which holds the hand-added `OPENAI_API_KEY` and the database password that matches the next volume |
| `make re` | `fclean` + `all` |

`down`, `logs` and `fclean` use `--profile '*'`, so they also reach services that are off by default (`worker`).

**Test database.** The backend tests delete what they find, so they run only on `POSTGRES_TEST_DB` (`wozu_test`), never on the app database `POSTGRES_DB`. `infra/db/create-test-db.sh` creates it, owned by `POSTGRES_USER`, with PostGIS (the schema has a `geography` column). It runs in the `db` container from two places: the image runs it once when the `db-data` volume is new (mounted as the single file `/docker-entrypoint-initdb.d/20-create-test-db.sh`, after the image's own `10_postgis.sh`), and `make test` runs it on every call (`docker compose exec`), so a volume created before the script gets the database too. It is idempotent, reads the names from the container environment, connects over the local socket (no password) and refuses a name that equals `POSTGRES_DB` or lacks `test` (the fixtures skip such a database). The tables come from the fixtures, which run `alembic` on `TEST_DATABASE_URL`.

**`.env.example` additions to the reference file** (every variable in `.env.example` has a comment there)

| Variable | Example | Used by |
| --- | --- | --- |
| `DOMAIN` | `localhost` | proxy (`server_name`), links |
| `HTTPS_PORT` / `HTTP_PORT` | `443` / `80` | host ports of the proxy |
| `FRONTEND_BASE_URL` | `https://localhost` | email links |
| `JWT_SECRET` | generated | api (BE-03 reads this name; the card said `SECRET_KEY`) |
| `INTERNAL_API_KEY` | generated | api, `/_internal/*` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `wozu` / generated / `wozu` | db; compose builds `DATABASE_URL` for api and worker from them |
| `POSTGRES_TEST_DB` | `wozu_test` | db (`infra/db/create-test-db.sh` creates it on a new volume, `make test` when it is missing); compose builds `TEST_DATABASE_URL` for the tests from it |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | `wozu` / generated | minio |
| `MINIO_EXTERNAL_ENDPOINT` | `https://localhost` | presigned URLs |
| `MINIO_BUCKET` | `files` | api, worker, minio-init |
| `SMTP_HOST` / `SMTP_PORT` / `MAIL_FROM` | `mailpit` / `1025` / `no-reply@wozu.local` | api |
| `GRAFANA_ADMIN_PASSWORD` | generated | grafana |
| `OPENAI_API_KEY` | empty, filled by hand | worker |
| `MODERATION_FAIL_OPEN` | `false` on defense day | worker |

Compose passes each service only the variables it needs (`environment:`), not the whole `.env`.

**Rules:** `.env` and `scripts/*.local` in `.gitignore`; nothing secret in `docker-compose.yml`, images or logs; with the Vault module, secrets move from `.env` to Vault and `.env` keeps only the Vault address and AppRole credentials.

## Infra modules

Each checklist mirrors the subject's bullets for that module; every box must be demonstrable live at the defense, or the module scores 0.

**M12 — Monitoring with Prometheus + Grafana (Major, 2, core)**

- [ ] Prometheus scrapes the API `/metrics` (via `prometheus-fastapi-instrumentator`; backend card BE-30), Postgres, Redis and container exporters
- [ ] Exporters and integrations configured in `prometheus.yml`, committed
- [ ] Custom Grafana dashboards provisioned from JSON files: API request rate, error rate, p95 latency, WebSocket connections, DB connections, Redis memory, container CPU / RAM
- [ ] Alerting rules: target down, API 5xx rate above a threshold, p95 latency above a threshold, disk almost full; show one alert firing live (stop a container)
- [ ] Grafana secured: admin password from `.env`, anonymous access off, served only over HTTPS at `/grafana`

**M13 — WAF / ModSecurity (hardened) + HashiCorp Vault (Major, 2, buffer)**

- [ ] Front proxy runs ModSecurity v3 with OWASP Core Rule Set, `SecRuleEngine On` (blocking, not detection only), paranoia level 2, tuned exclusions for our JSON API and WebSockets
- [ ] Demo: an SQL injection and an XSS probe return 403 and appear in the WAF audit log; normal app use triggers no false positives
- [ ] Vault in server mode (not dev mode) with file storage; init and unseal by a startup script; unseal keys kept out of Git
- [ ] API, worker and DB credentials, JWT secret, OpenAI and MinIO keys read from Vault (AppRole or Vault Agent rendering an env file); none left in `.env`
- [ ] Policies give each service read access only to its own path

**M14 — Health checks, status page, backups, disaster recovery (Minor, 1, buffer)**

- [ ] Health checks for every service in compose (the reference has them for API, DB, Redis, MinIO)
- [ ] Public status page showing each component green / red, fed by `/api/health` (without internal details)
- [ ] Automated daily `pg_dump` and bucket mirror, 7 copies kept
- [ ] Restore runbook in `docs/disaster-recovery.md`, tested: drop the DB volume, restore, app works

**Mandatory (no points, but rejection if missing):** HTTPS everywhere, one-command start, `.env` handling, mail catcher, pinned images, no secrets in Git.

## CI

Target for INF-06: GitHub Actions on PRs to `main`, with applicable backend, frontend and stack jobs passing plus one approving review before merge. Configure branch protection to enforce the required checks. This is the planned setup, not evidence that every job or protection rule is already active. CI is not a module; it protects integration and makes reviews visible.

| Job | Steps | Blocks merge |
| --- | --- | --- |
| backend | `ruff check`, `ruff format --check`, `pytest` with service containers `postgis/postgis:15-3.4` and `redis:7-alpine` | yes |
| frontend | `npm ci`, lint, type check, unit tests, `npm run build` | yes |
| stack | `docker compose build`, `docker compose config` (catches broken env references) | yes |

## Infra cards

IDs and titles as on the Trello board (snapshot in [backlog.md](../plan/backlog.md)); every INF card is owned by byul-byul and carries the DevOps label. INF-01 … INF-06 are in S1 and unblock the rest of the team.

| ID | Card | Done when | Depends on | Module | Sprint |
| --- | --- | --- | --- | --- | --- |
| INF-01 | Decide front proxy: Caddy or nginx + ModSecurity CRS (decided: nginx + ModSecurity CRS) | Decision in the decisions log; one config skeleton committed | — | M13 | S1 |
| INF-02 | Set up repo layout, root compose, Makefile and init-env script | Fresh clone → `make` → all containers healthy | INF-01 | Mandatory | S1 |
| INF-03 | Serve frontend, /api and /ws on one HTTPS origin | Frontend placeholder and API reachable at `https://localhost`; WebSocket connects; HTTP → HTTPS redirect | INF-02 | Mandatory | S1 |
| INF-04 | Expose MinIO at /files with bucket init and external endpoint | Browser PUT to a presigned URL succeeds over HTTPS | INF-03 | Mandatory | S1 |
| INF-05 | Add Mailpit at /mail for verification emails | Sign-up email visible in the inbox, link opens the frontend | INF-03 | Mandatory | S1 |
| INF-06 | Add CI for backend, frontend and stack with branch protection | Red CI blocks a PR | INF-02, BE-01, FE-01 | — | S1 |
| INF-07 | Pin images, slim API image, health checks for every service | `docker compose ps` all healthy; image smaller than the reference | INF-02, BE-01 | Mandatory, M14 | S2 |
| INF-08 | Add Prometheus with Postgres, Redis and container exporters | All targets `UP` | INF-03, BE-30 | M12 | S2 |
| INF-09 | Provision Grafana at /grafana with dashboards | Dashboards load after `make re` with no clicks | INF-08 | M12 | S2 |
| INF-10 | Add alert rules and a live alert demo | Stopping Redis fires an alert | INF-09 | M12 | S3 |
| INF-11 | Tune ModSecurity CRS in blocking mode | SQLi / XSS probes blocked, full app flow passes | INF-01, FE-32 | M13 | S3 |
| INF-12 | Run Vault in server mode with unseal script and AppRole | Vault in server mode with file storage; init and unseal by a startup script; unseal keys out of Git | INF-02 | M13 | S2 |
| INF-13 | Move all service secrets from .env to Vault | No secrets left in `.env` except Vault access | INF-12 | M13 | S3 |
| INF-14 | Add daily Postgres and bucket backups with 7-day retention | Daily `pg_dump` and bucket mirror run automatically, 7 copies kept | INF-07 | M14 | S3 |
| INF-15 | Write and test the restore runbook | Restore test passes: drop the DB volume, restore, app works (`docs/disaster-recovery.md`) | INF-14 | M14 | S3 |
| INF-16 | Build the public status page | Status page shows all components green | BE-31, INF-07 | M14 | S3 |

The README Instructions and Technical Stack sections (row 14 of the first draft) are card DOC-05 (byul-byul, S4); the clean-machine rehearsal is QA-01 (byul-byul, S4).
