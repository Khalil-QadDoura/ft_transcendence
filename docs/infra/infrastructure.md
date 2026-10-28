# ft\_transcendence — Infrastructure

Oct 27, 2026 · @byul-byul

## TL;DR

Infra owns four mandatory items and five module points. The reference already has a working compose stack (Caddy, API, Celery worker, Postgres + PostGIS, Redis, MinIO); what is missing is the frontend container, HTTPS for file storage, a mail catcher and everything for the modules.

- **Mandatory:** one command starts everything; every browser connection is HTTPS; `.env` stays out of Git with a complete `.env.example`; the evaluator can sign up without a paid email service.
- **Modules:** Prometheus + Grafana (Major, 2, core); WAF / ModSecurity + Vault (Major, 2, buffer); health check, status page and backups (Minor, 1, buffer).
- **Decide first (week 1):** the front proxy. If we will claim the WAF module, start with nginx + ModSecurity v3 + OWASP Core Rule Set as the only front door instead of Caddy; switching proxies late costs more than choosing now.
- **One origin for everything** (`https://localhost` at the defense): frontend at `/`, API at `/api`, WebSockets at `/ws`, files at `/files`, Grafana at `/grafana`, Mailpit at `/mail`. One certificate warning, no CORS, no mixed content.

## Services

Only the proxy publishes ports to the host; everything else stays on the internal Docker network. Pin every image tag (the reference uses `minio/minio:latest`).

| Service | Image | Purpose | Published | Status |
| --- | --- | --- | --- | --- |
| `proxy` | `caddy:2-alpine`, or `owasp/modsecurity-crs:nginx-alpine` if WAF | TLS, single origin, routing (+ WAF) | 443 (80 → redirect) | Exists (Caddy, API only) |
| `frontend` | Multi-stage: Node build → static files served by the proxy or `nginx:alpine` | React app | no | New |
| `api` | Built from `backend/` (Python 3.11 slim, multi-stage, no test deps) | FastAPI, runs migrations on start | no | Exists |
| `worker` | Same image as `api`, command `celery … worker -B` | Video moderation + beat for stuck videos | no | Exists, beat missing |
| `db` | `postgis/postgis:15-3.4` | PostgreSQL + PostGIS | no | Exists |
| `redis` | `redis:7-alpine` | Pub/sub, queues, rate limits, Celery broker | no | Exists |
| `minio` | `minio/minio` (pinned release) | Object storage for videos, avatars, logos | no (proxied at `/files`) | Exists, not proxied |
| `minio-init` | `minio/mc` | One-shot: create bucket `files`, set policies | no | New |
| `mailpit` | `axllent/mailpit` | Catches all outgoing mail, web inbox | no (proxied at `/mail`) | New |
| `prometheus` | `prom/prometheus` | Metrics scraping, alert rules | no | New (module) |
| `grafana` | `grafana/grafana` | Dashboards, provisioned from files | no (proxied at `/grafana`) | New (module) |
| exporters | `postgres-exporter`, `redis-exporter`, `cadvisor` or `node-exporter` | DB, Redis, container metrics | no | New (module) |
| `vault` | `hashicorp/vault` (server mode, file storage) | Secrets for API keys and credentials | no | Buffer module |
| `backup` | small image with `pg_dump` + `mc` + cron | Daily dumps of DB and bucket, 7-day retention | no | Buffer module |

We skip ELK: Elasticsearch is memory-hungry and risky on an evaluation laptop; Prometheus + Grafana gives the same 2 points with a lighter footprint.

## One origin over HTTPS

Everything the browser touches goes through one host and one certificate. Locally that is `https://localhost` with Caddy's internal CA (`tls internal`), so the evaluator accepts one warning once.

| Path | Upstream | Notes |
| --- | --- | --- |
| `/` | `frontend` static files | SPA fallback to `index.html` for client routes |
| `/api/*` | `api:8000` | FastAPI includes all routers under the `/api` prefix; the proxy does not strip paths |
| `/ws`, `/ws/game` | `api:8000` | WebSocket upgrade (Caddy and nginx handle it with the right headers) |
| `/files/*` | `minio:9000` | Bucket `files`; Host header passed through unchanged so presigned signatures match |
| `/grafana/*` | `grafana:3000` | `GF_SERVER_ROOT_URL=https://localhost/grafana/`, `serve_from_sub_path=true`, login required |
| `/mail/*` | `mailpit:8025` | `MP_WEBROOT=/mail/` |
| `/_internal/*`, `/metrics` | blocked | Prometheus scrapes them inside the Docker network only |
| `http://` any | redirect to `https://` |  |

```
{$DOMAIN} {
    tls internal                     # self-signed for localhost; real domain → automatic Let's Encrypt
    encode gzip

    @blocked path /_internal/* /metrics
    respond @blocked 404

    handle /api/*     { reverse_proxy api:8000 }
    handle /ws*       { reverse_proxy api:8000 }
    handle /files/*   { reverse_proxy minio:9000 }   # keep Host: presigned URLs are signed for {$DOMAIN}
    handle /grafana/* { reverse_proxy grafana:3000 }
    handle /mail/*    { reverse_proxy mailpit:8025 }
    handle {
        root * /srv/frontend
        try_files {path} /index.html
        file_server
    }
}
```

The same table translates one-to-one to nginx `location` blocks if we switch to the ModSecurity image.

## File storage over HTTPS

Recommendation: serve the bucket on the same origin at `/files/*` and presign URLs for `https://<domain>`. It keeps the reference's presigned-upload design, needs no second certificate and no CORS.

| Option | How | Pros | Cons |
| --- | --- | --- | --- |
| **A. Same origin, bucket path (recommended)** | Bucket named `files`; proxy routes `/files/*` → `minio:9000` with the Host header unchanged; API presigns with `MINIO_EXTERNAL_ENDPOINT=https://<domain>` | One cert, no CORS, minimal backend change | Bucket name is part of the public URL |
| B. Separate port, e.g. `https://<domain>:9443` | Second TLS listener → MinIO | Clean separation | Second self-signed warning the evaluator must also accept, or uploads fail silently; CORS needed |
| C. Upload through the API | Browser posts multipart to `/api/media/...`; API streams to MinIO | Server sees the bytes (real size, type, duration checks) | 50 MB requests through the API, more backend work |

**Required with option A:**

- The worker must download videos with the internal MinIO client (`minio:9000`), not through the external presigned URL: inside a container `https://localhost` is the container itself. The reference downloads via the external URL (`moderation_task.py`), so this is a backend card.
- `minio-init` creates the bucket and keeps it private; all access goes through presigned URLs (GET 5 min, PUT 15 min).
- On `confirm`, the API calls `stat_object` to check the file exists and its real size.
- Avatars need a stable read path: either short-lived presigned GET URLs returned in API responses, or a public-read prefix `files/avatars/*` (no secrets in avatars). Pick one with the backend Tech Lead.

## Email without a paid service

Add Mailpit and send mail over plain SMTP from the API; the evaluator opens `https://localhost/mail` to click the verification link. The reference only speaks the Brevo HTTP API and prints the link to the log when no key is set.

- `mailpit` container: SMTP on `mailpit:1025` (internal), web inbox on `8025`, proxied at `/mail` with `MP_WEBROOT=/mail/`.
- API env: `SMTP_HOST=mailpit`, `SMTP_PORT=1025`, `MAIL_FROM=no-reply@wozu.local`; keep Brevo as an optional sender when `BREVO_API_KEY` is set.
- Email links use `FRONTEND_BASE_URL` (`https://localhost`): `/verify-email?token=…`, `/reset-password?token=…`.
- Mention Mailpit in the README "Instructions" so the evaluator knows where verification emails land.

## One-command start and secrets

`make` must take a fresh clone to a running site: it creates `.env` from `.env.example` with random secrets when missing, then builds and starts the stack. The only value a human must add is `OPENAI_API_KEY` (moderation module).

```makefile
all: env up

env:
	@test -f .env || ./scripts/init-env.sh   # copies .env.example, fills SECRET_KEY, DB and MinIO passwords with openssl rand

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

test:
	docker compose run --rm api pytest -q

fclean: down
	docker compose down -v --rmi local

re: fclean all
```

**`.env.example` additions to the reference file**

| Variable | Example | Used by |
| --- | --- | --- |
| `DOMAIN` | `localhost` | proxy, links |
| `FRONTEND_BASE_URL` | `https://localhost` | email links |
| `MINIO_EXTERNAL_ENDPOINT` | `https://localhost` | presigned URLs |
| `MINIO_BUCKET` | `files` | api, worker, minio-init |
| `SMTP_HOST` / `SMTP_PORT` / `MAIL_FROM` | `mailpit` / `1025` / `no-reply@wozu.local` | api |
| `TEST_DATABASE_URL` | separate database `wozu_test` | tests |
| `GRAFANA_ADMIN_PASSWORD` | generated | grafana |
| `OPENAI_API_KEY` | empty, filled by hand | worker |
| `MODERATION_FAIL_OPEN` | `false` on defense day | worker |

**Rules:** `.env` and `scripts/*.local` in `.gitignore`; nothing secret in `docker-compose.yml`, images or logs; with the Vault module, secrets move from `.env` to Vault and `.env` keeps only the Vault address and AppRole credentials.

## Infra modules

Each checklist mirrors the subject's bullets for that module; every box must be demonstrable live at the defense, or the module scores 0.

**M12 — Monitoring with Prometheus + Grafana (Major, 2, core)**

- [ ] Prometheus scrapes the API `/metrics` (via `prometheus-fastapi-instrumentator`; backend card), Postgres, Redis and container exporters
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

GitHub Actions on every PR to `main`; branch protection requires all three jobs green plus one review. CI is not a module, but it keeps `main` always demo-ready and makes reviews visible in the history.

| Job | Steps | Blocks merge |
| --- | --- | --- |
| backend | `ruff check`, `ruff format --check`, `pytest` with service containers `postgis/postgis:15-3.4` and `redis:7-alpine` | yes |
| frontend | `npm ci`, lint, type check, unit tests, `npm run build` | yes |
| stack | `docker compose build`, `docker compose config` (catches broken env references) | yes |

## Infra cards

In this order; the first four unblock the rest of the team and should land in the first sprint.

| # | Card | Done when | Depends on | Module |
| --- | --- | --- | --- | --- |
| 1 | Decide front proxy: Caddy, or nginx + ModSecurity CRS | Decision in the decisions log; one config skeleton committed | — | M13 |
| 2 | Repo layout + root `docker-compose.yml` + `Makefile` + `init-env.sh` | Fresh clone → `make` → all containers healthy | 1 | Mandatory |
| 3 | One origin over HTTPS: `/`, `/api`, `/ws`, HTTP → HTTPS redirect | Frontend placeholder and API reachable at `https://localhost`; WebSocket connects | 2 | Mandatory |
| 4 | MinIO at `/files` + `minio-init` bucket + external endpoint env | Browser PUT to a presigned URL succeeds over HTTPS | 3 | Mandatory |
| 5 | Mailpit at `/mail` + SMTP env | Sign-up email visible in the inbox, link opens the frontend | 3 | Mandatory |
| 6 | Pin images, multi-stage API image without test deps, health checks everywhere | `docker compose ps` all healthy; image smaller than the reference | 2 | Mandatory, M14 |
| 7 | CI workflow (backend, frontend, stack) + branch protection | Red CI blocks a PR | 2 | — |
| 8 | Prometheus + exporters | All targets `UP` | 3, API `/metrics` card | M12 |
| 9 | Grafana at `/grafana` with provisioned dashboards | Dashboards load after `make re` with no clicks | 8 | M12 |
| 10 | Alert rules + live alert demo | Stopping Redis fires an alert | 8 | M12 |
| 11 | ModSecurity CRS tuning | SQLi / XSS probes blocked, full app flow passes | 1, app ready | M13 |
| 12 | Vault server, unseal script, AppRole, secrets moved | No secrets left in `.env` except Vault access | 2 | M13 |
| 13 | Backups + restore runbook + status page | Restore test passes; status page shows all green | 6 | M14 |
| 14 | README: Instructions, Technical Stack, infra parts of Modules | A teammate follows the README on a clean machine | all | Mandatory |
