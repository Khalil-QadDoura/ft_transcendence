# ft\_transcendence — Infrastructure

Oct 27, 2026 · updated Nov 17, 2026 · @byul-byul

## TL;DR

Infra owns four mandatory items and five module points. The reference already has a working compose stack (Caddy, API, Celery worker, Postgres + PostGIS, Redis, MinIO); what is missing is the frontend container, HTTPS for file storage, a mail catcher and everything for the modules.

- **Mandatory:** one command starts everything; every browser connection is HTTPS; `.env` stays out of Git with a complete `.env.example`; the evaluator can sign up without a paid email service.
- **Modules:** Prometheus + Grafana (Major, 2, core); WAF / ModSecurity + Vault (Major, 2, buffer); health check, status page and backups (Minor, 1, buffer).
- **Front proxy decided (2026-11-04, INF-01):** nginx + ModSecurity v3 + OWASP Core Rule Set is the only front door instead of Caddy. Configuration: [infra/proxy/](../../infra/proxy/README.md).
- **File storage decided (2026-11-09, INF-04):** MinIO on the same origin at `/files`, private bucket `files` created by the one-shot `minio-init`, uploads and video reads through presigned URLs; see File storage over HTTPS.
- **Monitoring (2026-11-15, INF-08):** Prometheus scrapes the API, postgres-exporter, redis-exporter and cAdvisor inside the Docker network; no host port, no proxy route; metrics kept 30 days, at most 1 GB; `make metrics-check`. See M12 under Infra modules.
- **Dashboards (2026-11-15, INF-09):** Grafana at `/grafana/` behind the proxy, login `admin` with the generated `GRAFANA_ADMIN_PASSWORD`, no anonymous access, no sign-up, no public dashboards or snapshots, no plugins and no calls to grafana.com; datasource and two dashboards (WOZU API, WOZU Infrastructure) provisioned read-only from `infra/grafana/`; `make grafana-check`. See M12 under Infra modules.
- **One origin for everything** (`https://localhost` at the defense): frontend at `/`, API at `/api`, WebSockets at `/ws`, files at `/files`, Grafana at `/grafana`, Mailpit at `/mail`. One certificate warning, no CORS, no mixed content.

## Front proxy (decided 2026-11-04)

nginx + ModSecurity v3 + OWASP Core Rule Set (CRS), image `owasp/modsecurity-crs:nginx-alpine`, decided in card INF-01 (byul-byul) and logged in the decisions log of the overview. Caddy from the reference is not used. Reason: the WAF module (M13) needs ModSecurity, and switching proxies late costs more than choosing now. INF-03 implements the routes below as nginx `location` blocks; INF-11 tunes CRS in blocking mode.

## Services

Only the proxy publishes ports to the host; everything else stays on the internal Docker network. All services are in the root `docker-compose.yml` (compose project `wozu`) since INF-02. Every image is pinned by tag and digest and every long-running service has a health check, with the exemptions listed there (INF-07, see Images, health checks and logs); digests below are shortened to 12 characters.

| Service | Image | Purpose | Published | Status |
| --- | --- | --- | --- | --- |
| `proxy` | `owasp/modsecurity-crs:4.30.0-nginx-alpine-202610180210@sha256:873ce68a658d` | TLS, single origin, routing, WAF | 443 (80 → redirect); host ports set by `HTTPS_PORT` / `HTTP_PORT` | In compose (INF-02); health check, starts after its upstreams are healthy |
| `frontend` | Built from `frontend/` (FE-01 Dockerfile, stage `preview`: `node:24-alpine@sha256:116b800c3754` build → `nginx:1.28-alpine@sha256:a8b39bd9cf0f`); site config `infra/frontend/default.conf` mounted for the SPA fallback and `/healthz` | React app | no | In compose (INF-02); health check |
| `api` | Built from `backend/`, stage `runtime` (`python:3.11-slim@sha256:07d4824036af`, multi-stage, no test deps, non-root) | FastAPI, runs migrations on start; waits for `db` and `redis` to be healthy and `minio-init` to exit 0 | no | In compose, `/api/health` health check (Python `urllib`; the image has no curl) |
| `worker` | Same image as `api` (stage `runtime`), command `celery -A app.worker.celery_app worker -B` | Video moderation + beat for stuck videos | no | In compose behind the `worker` profile, off by default: the Celery app exists since BE-07, but there is no task to run until BE-29 adds the moderation task; no health check until it runs by default |
| `api-test` | Built from `backend/`, stage `test` (`runtime` + `requirements-dev.txt`) | Tests only: ruff + pytest of `make test`, run with `compose run --rm` | no | In compose behind the `test` profile; one-shot, no health check |
| `db` | `imresamu/postgis:15-3.4@sha256:44d4443d107a` (PostgreSQL 15 + PostGIS 3.4 from the docker-postgis sources, amd64 + arm64; every `postgis/postgis` tag is amd64 only, so Apple Silicon would run it emulated) | PostgreSQL + PostGIS; app database `POSTGRES_DB` and test database `POSTGRES_TEST_DB` | no | In compose, `pg_isready` health check |
| `redis` | `redis:7.4.12-alpine@sha256:7f7d30b7fdd0` | Pub/sub, queues, rate limits, Celery broker; api and worker use database 0 (`REDIS_URL`) | no | In compose, `redis-cli ping` health check |
| `redis-test` | Same image as `redis` (one YAML anchor) | Tests only: the Redis of `make test` (`TEST_REDIS_URL` and `REDIS_URL` of the pytest run); no persistence (`--save "" --appendonly no`, `tmpfs` on `/data`), no volume, no route, nothing depends on it | no | In compose behind the `test` profile, started only by `make test`; `redis-cli ping` health check for `up --wait` |
| `minio` | `pgsty/minio:RELEASE.2026-08-04T00-00-00Z@sha256:b6bfe7239bfc` (the official `minio/minio` and `minio/mc` images left Docker Hub on 2025-10-23) | Object storage for videos, avatars, logos | no, console included (proxied at `/files`) | In compose; health check |
| `minio-init` | Same image as `minio`, which ships `mc` | One-shot: create bucket `files`, set its anonymous policy, exit 0 | no | In compose (INF-04); starts once `minio` is healthy; `api` starts after it completes |
| `mailpit` | `axllent/mailpit:v1.33.1@sha256:aef2aacc11f0` | Catches all outgoing mail, web inbox | no (proxied at `/mail`) | In compose (INF-02); health check |
| `prometheus` | `prom/prometheus:v3.16.0@sha256:e04987641b57` | Metrics scraping (alert rules: INF-10); data in the `prometheus-data` volume, 30 days, at most 1 GB | no, and no proxy route | In compose (INF-08); `/-/ready` health check |
| `grafana` | `grafana/grafana:13.3.1@sha256:0615ec4fbd40` | Dashboards, datasource and dashboards provisioned read-only from `infra/grafana/`; data (users, sessions) in the `grafana-data` volume | no (proxied at `/grafana`) | In compose (INF-09); `/api/health` health check; starts once `prometheus` is healthy |
| `postgres-exporter` | `prometheuscommunity/postgres-exporter:v0.20.1@sha256:ac5ec343104f` | PostgreSQL metrics for Prometheus (`pg_up`, connections, sizes) | no | In compose (INF-08); health check; starts once `db` is healthy |
| `redis-exporter` | `oliver006/redis_exporter:v1.97.0@sha256:f5f903fbe775` | Redis metrics for Prometheus (`redis_up`, memory, clients) | no | In compose (INF-08); no health check (scratch image, see Exemptions); starts once `redis` is healthy |
| `cadvisor` | `ghcr.io/google/cadvisor:v0.60.6@sha256:b8e7d1093144` | CPU and memory of every container, by compose service | no | In compose (INF-08); `/healthz` health check; read-only host mounts, not privileged |
| `vault` | `hashicorp/vault` (server mode, file storage) | Secrets for API keys and credentials | no | Buffer module |
| `backup` | small image with `pg_dump` + `mc` + cron | Daily dumps of DB and bucket, 7-day retention | no | Buffer module |

We skip ELK: Elasticsearch is memory-hungry and risky on an evaluation laptop; Prometheus + Grafana gives the same 2 points with a lighter footprint.

## Images, health checks and logs (INF-07)

**Pinned images.** Every image is written as `name:tag@sha256:<digest>`: in `docker-compose.yml` and in every Dockerfile `FROM` (build and runtime stages). The tag says which version it is; the digest is what Docker pulls, so a tag that moves (`redis:7-alpine`, `python:3.11-slim`) or is overwritten cannot change the stack before the defense. The digest is the one of the multi-arch index (`docker buildx imagetools inspect <name:tag>`), so Apple Silicon laptops and the amd64 CI runner get the same build. To bump an image, change tag and digest together in one commit. Prometheus and the three exporters are pinned the same way since INF-08, Grafana since INF-09 (see M12 under Infra modules); Vault follows in its own card (INF-12).

| Image | Before INF-07 | Pinned |
| --- | --- | --- |
| proxy | `owasp/modsecurity-crs:4.30.0-nginx-alpine-202610180210`, by digest | unchanged, `@sha256:873ce68a658d` |
| db | `imresamu/postgis:15-3.4`, by digest | unchanged, `@sha256:44d4443d107a` |
| minio, minio-init | `pgsty/minio:RELEASE.2026-08-04T00-00-00Z`, by digest | unchanged, `@sha256:b6bfe7239bfc` |
| redis, redis-test | `redis:7-alpine` (moving tag) | `redis:7.4.12-alpine@sha256:7f7d30b7fdd0`, the build `7-alpine` pointed to on 2026-11-12 |
| mailpit | `axllent/mailpit:v1.33.1` | `…:v1.33.1@sha256:aef2aacc11f0` |
| backend `FROM` (build, runtime) | `python:3.11-slim` | `python:3.11-slim@sha256:07d4824036af` (Python 3.11.18) |
| frontend `FROM` (build) | `node:24-alpine` | `node:24-alpine@sha256:116b800c3754` (Node 24.22.3) |
| frontend `FROM` (preview) | `nginx:1.28-alpine` | `nginx:1.28-alpine@sha256:a8b39bd9cf0f` (nginx 1.28.3) |

**`make images-check`** (`scripts/images-check.sh`) enforces the rule: it reads every compose service of every profile (`docker compose --profile '*' config --no-interpolate`, YAML anchors resolved, no `.env` needed) and every `FROM` in the repository's Dockerfiles, skips a `FROM` that names an earlier stage (`FROM runtime AS test`), and fails when an image has no `@sha256:` digest, no tag, or the tag `latest`, naming each offender (`FAIL  docker-compose.yml service redis: redis:7-alpine (no @sha256 digest)`). Since INF-06 it also reads the images of `.github/workflows/*.yml`, with file and line, and the CI `stack` job runs it (see CI, Image pins).

**Database image, a deliberate choice (byul-byul, 2026-11-12).** `imresamu/postgis:15-3.4` is a frozen build (PostgreSQL 15.8); `15-3.5` exists. The stack stays on 15-3.4, pinned by the same digest as the CI backend job, so the tests and the site run the same server; a move to 15-3.5 would be its own card with a dump and restore test.

**API image.** `backend/Dockerfile` has three stages:

| Stage | From | Contents | Used by |
| --- | --- | --- | --- |
| `build` | `python:3.11-slim` | a virtual environment `/venv` with `requirements.txt` only | the next stage |
| `runtime` | `python:3.11-slim` | `/venv`, `app/`, `alembic/`; user `app` (uid 10001); no pytest, ruff or other dev tool, no compiler, no pip cache, no tests (`.dockerignore`) | `api`, `worker` (`target: runtime`) |
| `test` | `runtime` | plus `requirements-dev.txt` (pytest, ruff, httpx2, aiosmtpd, websockets), same user | `api-test`, i.e. `make test`, with the code and tests mounted read-only |

`make test` used to `pip install` the dev tools as root into a throwaway api container on every run; it now runs `api-test` as the same non-root user as production, and the tools are cached in the image. Sizes (`docker image ls`, unpacked; compressed content size in brackets), 2026-11-12:

| Image | Size |
| --- | --- |
| Reference `backend/fastapi` (one stage, test requirements and ffmpeg installed) | 1.58 GB (371 MB) |
| api before INF-07 (BE-01 multi-stage, unnamed runtime stage) | 465 MB (99 MB) |
| api `runtime` after INF-07 | 466 MB (99 MB) |
| `api-test` (`test` stage) | 522 MB (114 MB) |

The runtime image is 70 % smaller than the reference; the slimming came with BE-01 (Khalil), and INF-07 keeps it, names the stage and moves the test tools into their own stage. The 1 MB is the newer Python patch release in the pinned base. `websockets` is in the runtime image as a dependency of `uvicorn[standard]`, not from `requirements-dev.txt`. The reference image has ffmpeg; ours does not, which BE-29 must check for the moderation worker.

**Health checks.** Each long-running service checks itself with a tool its image already has; nothing is installed for it. All share one timing (`x-healthcheck` in compose, decided on the card on 2026-11-08): while a container starts, a check every 2 s (`start_interval`) for up to 30 s (`start_period`), failures not counted, so `make` returns as soon as everything is ready; after that one check per 30 s, 3 s timeout, unhealthy after 3 failures in a row. The 30 s interval keeps the api log at one `GET /api/health` line per 30 s instead of one per 5 s. `start_interval` needs Docker Engine 25 or newer.

| Service | Check | What a pass shows | Waits for (`depends_on`) |
| --- | --- | --- | --- |
| `proxy` | `curl -fsk -H 'Host: localhost' https://127.0.0.1:8443/healthz` (the image's own location, no access log) | nginx runs with our config, ModSecurity loaded and the certificate served over TLS. The image's built-in check uses `curl` without `-f`, which also passes on a 404. The `Host` header matters: with the bare IP, CRS rule 920350 writes a 1.5 kB audit entry per check (about 5 MB a day) | `frontend`, `api`, `minio`, `mailpit`, `grafana`: healthy |
| `frontend` | `curl -fs http://127.0.0.1/healthz`: `location = /healthz` in `infra/frontend/default.conf` serves `index.html`, no access log | nginx serves the built app | — |
| `api` | Python `urllib` GET `http://127.0.0.1:8000/api/health`, 200 | migrations ran (`alembic upgrade head` precedes uvicorn) and the app answers | `db`, `redis`: healthy; `minio-init`: completed successfully |
| `db` | `pg_isready -h 127.0.0.1 -U $POSTGRES_USER -d $POSTGRES_DB` | the server accepts TCP connections. Over TCP because while the image initialises a new volume it runs a temporary server on the Unix socket only | — |
| `redis`, `redis-test` | `redis-cli ping \| grep -qx PONG` | the server answers commands; an error reply such as `LOADING` fails | — |
| `minio` | `curl -fs http://127.0.0.1:9000/minio/health/live` | the S3 server is up | — |
| `mailpit` | `/mailpit readyz` (also the image's own check) | SMTP and web UI are ready | — |
| `prometheus` | `wget -qO- http://127.0.0.1:9090/-/ready` (busybox wget in the image) | the server has loaded its config and TSDB and serves queries | — (a target that is not up yet only shows as down) |
| `postgres-exporter` | `wget -q -O /dev/null http://127.0.0.1:9187/` (its landing page) | the exporter serves; whether it reaches the database is `pg_up`, checked by `make metrics-check` | `db`: healthy |
| `cadvisor` | `wget -q -O /dev/null http://127.0.0.1:8080/healthz` (what the image's own check asks) | cAdvisor runs and serves | — |
| `grafana` | `wget -q -O /dev/null http://127.0.0.1:3000/api/health` (busybox wget in the image) | Grafana serves and reaches its database (the SQLite file in `grafana-data`); whether the datasource answers is checked by `make grafana-check` | `prometheus`: healthy |

`depends_on` with `condition: service_healthy` is used where the order matters: the api runs its migrations at start and needs the database and Redis; `minio-init` needs a live MinIO; the proxy could start without its upstreams (it resolves them per request) but then answers 502 until they are up, so it waits and the site works as soon as `make` returns. `service_completed_successfully` is for the one-shot `minio-init`: the api hands out URLs for the bucket it creates, and `docker compose up --wait` accepts an exited container only when another service waits for it this way. `make up` runs `docker compose up -d --build --wait --wait-timeout 300`, so `make` fails if a service is not healthy within 5 minutes or exits.

**Exemptions.**

| Service | Why no health check |
| --- | --- |
| `minio-init` | One-shot job: exits 0 after creating the bucket; the api waits for that exit code instead |
| `api-test` | One-shot: `make test` runs it with `compose run --rm` and removes it |
| `redis-exporter` | The image is built `FROM scratch`: only the exporter binary, no shell and no HTTP client, and the binary has no check subcommand; nothing is added to it (INF-08). `make metrics-check` covers it: the `redis` target must be up and `redis_up` must be 1. It starts once `redis` is healthy |
| `worker` | Off by default (profile `worker`) because there is no task to run until BE-29 adds the moderation task; the Celery app exists since BE-07 (`backend/app/worker/celery_app.py`), and with `--profile worker` the worker starts on the runtime image as uid 10001 and reaches ready. No health check until it runs by default; then it gets one, e.g. `celery -A app.worker.celery_app inspect ping -d celery@$HOSTNAME` |

**Logs.** Every service logs to stdout / stderr, kept by Docker's `json-file` driver; one compose anchor `x-logging` gives every service the same rotation: `max-size: 10m`, `max-file: 3`, at most 30 MB per container. Docker deletes the oldest file when the third is full, so the caps bound the disk use, not the age: on a quiet stack the files fill slowly and lines can stay longer than 30 days, and they go away only when the container is removed (`make down`, or a `make` that recreates the container). The Privacy Policy's "at most 30 days" for logs and metrics (PO decision of 2026-11-13) is therefore not yet guaranteed by this setting; the mechanism that enforces it is still open. The proxy access log holds client IP addresses. `docker inspect --format '{{json .HostConfig.LogConfig}}' <container>` shows the caps.

## One origin over HTTPS

Everything the browser touches goes through one host and one certificate. Locally that is `https://localhost` with a self-signed certificate from `infra/proxy/scripts/gen-cert.sh`, so the evaluator accepts one warning once.

| Path | Upstream | Notes |
| --- | --- | --- |
| `/` | `frontend:80` | The frontend container does the SPA fallback to `index.html` for client routes; a missing `/assets/*` file is a 404, not `index.html` |
| `/api/*` | `api:8000` | FastAPI includes all routers under the `/api` prefix; the proxy does not strip paths |
| `/ws`, `/ws/game` | `api:8000` | WebSocket upgrade: HTTP/1.1, `Upgrade` and `Connection` headers, long read timeout |
| `/files/*` | `minio:9000` | Bucket `files`; URI and Host header passed through unchanged so presigned signatures match; 60 MB body limit |
| `/grafana/*` | `grafana:3000` | `GF_SERVER_ROOT_URL=${FRONTEND_BASE_URL}/grafana/` (`https://localhost/grafana/`, with the port when `HTTPS_PORT` is not 443), `serve_from_sub_path=true`, URI passed unchanged, login required; Grafana Live (WebSocket at `/grafana/api/live/ws`) gets the upgrade headers of the server block |
| `/mail/*` | `mailpit:8025` | `MP_WEBROOT=/mail/` |
| `/_internal*`, `/metrics*`, `/api/_internal*`, `/api/metrics*` | blocked (404) | Prometheus scrapes them inside the Docker network only |
| `http://` any | redirect to `https://` | 301, path and query kept |

The table translates one-to-one to the `location` blocks in `infra/proxy/templates/conf.d/default.conf.template`. ModSecurity covers all of them and runs in `DetectionOnly` until INF-11 switches it to blocking. The image runs unprivileged and listens on 8080 and 8443 inside the container, so compose publishes `443:8443` and `80:8080`. `HTTPS_PORT` and `HTTP_PORT` in `.env` change the host side; the redirect then carries the HTTPS port (`http://localhost:8080/` → `https://localhost:8443/`). `infra/proxy/README.md` lists which files are ours and which come from the image.

**Internal routes stay inside (INF-03).** The API mounts `/_internal/*` at the root, next to `/api`, behind the `X-Internal-Key` header (`backend/app/core/internal.py`); `/metrics` (BE-30) is planned at the root too. The proxy answers 404 itself for `/_internal` and `/metrics` and everything below them, and also for `/api/_internal` and `/api/metrics`: no route lives there today, but a router mounted under `/api` by mistake would otherwise be public. The match runs on the path after nginx decodes and normalizes it, so `/api/../_internal`, `//_internal` and `/%5Finternal` are 404 too. Inside the Docker network the routes work as before (`http://api:8000/_internal/health/db` with the key → 200). The rule for backend cards: internal routes go under `/_internal`, never in the `/api` router.

**Redirects keep the host port.** nginx's own trailing-slash redirects (`/mail` → `/mail/`, also `/files`, `/api`, `/grafana`, and the frontend container's `/assets` → `/assets/`) send a relative `Location` (`absolute_redirect off` in both nginx configs). An absolute one would drop a non-default `HTTPS_PORT`, and the frontend container, which sees plain HTTP behind the proxy, would even send the browser to `http://`. Checked with `HTTPS_PORT=18443`: `/mail` lands on `https://localhost:18443/mail/`.

**WebSockets.** `location /ws` covers `/ws` and `/ws/game`: HTTP/1.1 to the API with the `Upgrade` and `Connection` headers, no buffering, one-hour read and send timeouts. The API's `/ws` (BE-06) accepts every upgrade first and only then checks the ticket: with no valid ticket the browser gets `101 Switching Protocols`, then a close with code 1008. So a ticketless handshake through the proxy must end in 101. A 403 means the route is missing or refused it before the handshake (uvicorn's answer to a WebSocket with no route), and a 400 or 502 page means nginx itself failed.

**Check:** `make https-check` (`infra/proxy/smoke-test.sh`) runs against the running stack, from the host over HTTPS with the proxy certificate, on the host ports compose published: deep links (`/friends`, `/login`, `/game/rules`) → `index.html`, a missing asset → 404, a real asset → 200 JavaScript; `/api/health` → 200; a WebSocket handshake on `/ws` with no ticket (HTTP/1.1, 3 s limit: only 101 with a matching `Sec-WebSocket-Accept` passes; 403, 404, 426, 502, a timeout or `index.html` fail; `WS_PATH=/ws-missing make https-check` shows the failure); the HTTP → HTTPS redirect with path and query; the trailing-slash redirects with the host port; the internal routes above, sent with the real `X-Internal-Key`, → 404 from the proxy, and the same route inside the network → 200; only the proxy publishes host ports. INF-06 CI runs it.

## File storage over HTTPS

Recommendation: serve the bucket on the same origin at `/files/*` and presign URLs for `https://<domain>`. It keeps the reference's presigned-upload design, needs no second certificate and no CORS.

| Option | How | Pros | Cons |
| --- | --- | --- | --- |
| **A. Same origin, bucket path (recommended)** | Bucket named `files`; proxy routes `/files/*` → `minio:9000` with the Host header unchanged; API presigns with `MINIO_EXTERNAL_ENDPOINT=https://<domain>` | One cert, no CORS, minimal backend change | Bucket name is part of the public URL |
| B. Separate port, e.g. `https://<domain>:9443` | Second TLS listener → MinIO | Clean separation | Second self-signed warning the evaluator must also accept, or uploads fail silently; CORS needed |
| C. Upload through the API | Browser posts multipart to `/api/media/...`; API streams to MinIO | Server sees the bytes (real size, type, duration checks) | 50 MB requests through the API, more backend work |

Option A is implemented in INF-04 (2026-11-09).

**Request path.** The browser sends `PUT https://localhost/files/<key>?X-Amz-…`; the proxy's `location /files/` passes it to `minio:9000` with the URI exactly as sent: no prefix strip, no rewrite, no decoding. MinIO uses path-style addressing, where the first path segment is the bucket, so the bucket is named `files` and the route prefix and the bucket name are the same thing. `MINIO_DOMAIN` stays unset (no virtual-host style). Changing `MINIO_BUCKET` therefore also needs a new proxy route; `.env.example` says to keep it `files`.

**Host header.** A presigned URL signs the `host` header (`X-Amz-SignedHeaders=host`), and MinIO recomputes the signature from the Host it receives. The proxy sets `Host $http_host`, the value the browser sent, port included. `$host` would drop a non-default port (`localhost:8443` → `localhost`), and every URL signed for `https://localhost:8443` would fail with `SignatureDoesNotMatch`. So with a non-default `HTTPS_PORT`, `MINIO_EXTERNAL_ENDPOINT` must carry the same port (`https://localhost:8443`); checked with `HTTPS_PORT=8443`.

**No CORS.** The frontend and the files are both on `https://localhost` (same scheme, host and port), so an upload with `fetch` is a same-origin request: no preflight, and the bucket has no CORS configuration.

**Region.** The API signs with `MINIO_REGION=us-east-1`. Without a region, the MinIO Python SDK first asks the endpoint for the bucket region (`GET /files?location=`). For the signing client that endpoint is `https://localhost`, which inside the api container is the container itself, so the call fails and no URL is signed (checked with `minio` 7.2.20). us-east-1 is the region MinIO reports when the server sets none.

**Two clients (contract for BE-07, BE-08, BE-29).** The backend has no storage settings yet; compose already passes these to `api` and `worker` (names as in the reference `minio_client.py`):

| Variable | Value | Set in |
| --- | --- | --- |
| `MINIO_ENDPOINT` | `minio:9000` (plain HTTP inside the Docker network) | compose, like the `db` host in `DATABASE_URL` |
| `MINIO_EXTERNAL_ENDPOINT` | `https://localhost` (with the port when it is not 443) | `.env` |
| `MINIO_BUCKET` | `files` | `.env` |
| `MINIO_REGION` | `us-east-1` | `.env` (compose falls back to `us-east-1` for an older `.env`) |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | `.env`; INF-13 replaces them with a dedicated service account read from Vault |

| Client | Built from | Used for |
| --- | --- | --- |
| internal | `MINIO_ENDPOINT`, `secure=False` | Everything the server does itself: `stat_object` on `confirm` (real size, file exists), the worker's video download (BE-29; the reference downloads through the external URL, which cannot work from a container), deletes |
| external | `MINIO_EXTERNAL_ENDPOINT` + `MINIO_REGION`, `secure=True` | Signing only: `presigned_put_object` (15 min by default, at most 1 h), `presigned_get_object` (5 min by default, at most 1 h; `MAX_URL_EXPIRES_SEC` in `backend/app/media/constants.py`). It never sends a request |

**Bucket init.** The one-shot `minio-init` service runs `infra/minio/init-bucket.sh` on every `make`:

1. Waits for MinIO with `mc ready` under a 60-second `timeout`; exits 1 if MinIO never comes up.
2. Creates the bucket with `mc mb --ignore-existing` when it is missing, else logs "already exists".
3. Replaces the anonymous policy with `mc anonymous set-json`, prints it and exits 0.

- **Image:** the `minio` server image itself, `pgsty/minio:RELEASE.2026-08-04T00-00-00Z@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372`, defined once in compose (`x-minio-image`). It ships `/usr/bin/mc` of the same release (checked with `mc --version`) for amd64 and arm64, so there is one image to pin and bump instead of two, and no `minio/*` or `pgsty/mc` image.
- **Credentials** reach `mc` only through `MC_HOST_wozu` in the container environment: never on a command line, in a config file or in the log. They must be URL-safe; `init-env.sh` generates hex.
- **Restart and `make`:** `restart: "no"`. It starts once `minio` is healthy (INF-07). `api` depends on it with `condition: service_completed_successfully`. The API hands out URLs for the bucket, so it should start after the bucket exists; and `docker compose up --wait` accepts an exited container only when another service depends on it that way. Without it, `make up` fails with `container wozu-minio-init-1 exited (0)`.

**Read access (proposal to Khalil for BE-08, pending his review of the INF-04 PR).** The bucket is private; the policy grants anonymous `s3:GetObject` on two prefixes only:

| Keys | Anonymous access | How the frontend reads them |
| --- | --- | --- |
| `avatars/*`, `logos/*` | Download only: no listing, no upload | Stable URL `https://<host>/files/avatars/<uid>/<uuid>.jpg` in `avatar_url` / `logo_url` |
| Everything else, e.g. `users/<uid>/intro/<uuid>.mp4` | None | Presigned GET from the API, 5 min by default, at most 1 h (`MAX_URL_EXPIRES_SEC`) |
| The bucket itself | No listing for anyone (`s3:ListBucket` is not granted) | — |

Every write needs a presigned PUT. Reasons: avatars and logos are shown publicly anyway (profiles, friends lists, job cards); a stable URL lets the browser cache the image and never expires inside an open page; the API does not sign one URL per avatar in every list response. Videos stay private: they are personal data under moderation (privacy policy). The reference already uses the keys `avatars/{uid}/{uuid}.{ext}` and `logos/{cid}/{uuid}.{ext}`, so BE-08 needs no key change; the list is `PUBLIC_PREFIXES` in `init-bucket.sh`. If Khalil prefers signed GETs for avatars too, `PUBLIC_PREFIXES` becomes empty and the bucket is fully private.

**Security headers (found by Khalil in the INF-04 review).** MinIO answers with the `Content-Type` the uploader sent, and nothing can stop a logged-in user from sending `text/html` with the PUT to their own upload link: BE-07 and BE-08 refuse such a file on `confirm`, after it is stored. Without more, `https://localhost/files/avatars/...` (public) or a video's presigned GET would open that page as a page of our origin, with its scripts able to call `/api` as the viewer. `location /files/` therefore adds, with `always` so error answers carry them too:

| Header | Effect |
| --- | --- |
| `Content-Security-Policy: sandbox` | A document opened from `/files` gets a unique opaque origin with scripts, forms and popups off, so it cannot run code as `https://localhost`. CSP applies to documents and workers only: `<img>` and `<video>` that load these files are unaffected (checked in headless Chrome: an `<img>` loaded, an uploaded HTML page's script did not run) |
| `X-Content-Type-Options: nosniff` | The browser keeps the declared type instead of guessing one from the bytes, so e.g. an "image" is never run as a script or style |

MinIO already sends its own `nosniff`; the proxy hides it (`proxy_hide_header`) and sends one copy. nginx drops every inherited `add_header` in a location that has its own; `nginx -T` in the proxy shows none at `http` or `server` level (the `Server` header comes from `more_set_headers`, which is not affected), so `/files` loses nothing.

**Check:** `make files-check` (`infra/minio/smoke-test.sh`) runs against the running stack: it signs URLs the way the API will (from a container on the compose network, `minio` SDK, the api container's `MINIO_*` values), then from the host over HTTPS with the proxy certificate checks a presigned PUT and GET (200, same content), a tampered signature (403 `SignatureDoesNotMatch`), anonymous GET under `avatars/` (200), anonymous GET of a video, listing and anonymous PUT (403 each). The presigned GET, the anonymous GET and an HTML page uploaded through a presigned PUT as `text/html` (served as `text/html`) must each carry both security headers exactly once. It ends by printing a snippet for the Chrome console with fresh presigned URLs, which shows a same-origin upload from the browser with no CORS error. It needs network access to install the SDK. The script removes its own test objects; the browser check leaves one 5-byte object, `videos/inf04-browser.txt`, which the next run overwrites.

## Email without a paid service

Mailpit catches every email the API sends over plain SMTP; the evaluator opens `https://localhost/mail` to click the verification link. The reference only speaks the Brevo HTTP API and prints the link to the log when no key is set. Implemented in INF-05 (service and env) with the SMTP sender of BE-03 (`backend/app/core/mailer.py`).

- `mailpit` container (`axllent/mailpit:v1.33.1`): SMTP on `mailpit:1025` and the web inbox on `8025`, both on the internal network only, no host ports. The proxy serves the inbox at `/mail/` (`MP_WEBROOT=/mail/`), so its API is at `/mail/api/v1/…`.
- API settings, passed by compose and read by `backend/app/core/config.py` under the same names: `SMTP_HOST=mailpit`, `SMTP_PORT=1025`, `MAIL_FROM=no-reply@wozu.local`, `FRONTEND_BASE_URL=https://localhost`.
- **No Brevo (PO decision 2026-11-08):** the defense uses Mailpit only. The backend still has an optional `BREVO_API_KEY` setting (Brevo replaces SMTP when it is set); compose does not pass it and `.env.example` does not list it, so the API always sends over SMTP.
- Email links use `FRONTEND_BASE_URL`: `/verify-email?token=…`, later `/reset-password?token=…` (BE-04). With a non-default `HTTPS_PORT` the port goes into `FRONTEND_BASE_URL` too (`https://localhost:18443`), or the link misses it.
- For DOC-05: the README "Instructions" say that verification emails land at `https://localhost/mail`.

**Flow.** `POST /api/auth/register` answers 202 and sends the email in the background. Mailpit keeps it; its sender is `MAIL_FROM`, its link `FRONTEND_BASE_URL/verify-email?token=<JWT>`. The link opens the frontend (the proxy's `/` route, `index.html`); its `/verify-email` page (FE-04) calls `GET /api/auth/verify?token=…`. Login answers 403 until then, 200 after.

**Check:** `make mail-check` (`infra/mailpit/smoke-test.sh`) runs the flow against the running stack, from the host over HTTPS through the proxy only: the four settings as the API's own `Settings` reads them, no Brevo key; sign-up of `inf05-check-<timestamp>@example.com` → 202; login → 403; the message found through the Mailpit API with the right sender and link; the link → 200 `index.html`; the token → `/api/auth/verify` 200; login → 200 with tokens. It deletes its message through the Mailpit API; the test user stays in the database, one per run. The address uses `example.com` (reserved, RFC 2606): the API rejects `example.test`, because the email validator refuses special-use domains. Sign-up allows 5 requests per minute per IP, so the check can run about five times a minute.

**Known limitation: the inbox has no login.** Anyone who reaches the site can open `/mail`, read every caught email and use its links: verify someone else's account, and once BE-04 lands, reset someone else's password. The API at `/mail/api/v1` is just as open (read, delete). Acceptable for the defense: the stack runs on the evaluator's machine for `localhost` and holds test accounts only. A shared or public deployment would need a login in front of the inbox (Mailpit's `MP_UI_AUTH_FILE`, a password file for the inbox and its API) or a real mail service instead of Mailpit. Caught mail lives inside the `mailpit` container (no volume): a recreated container starts with an empty inbox.

## One-command start and secrets

`make` must take a fresh clone to a running site: it creates `.env` from `.env.example` with random secrets when missing, then builds and starts the stack. The only value a human must add is `OPENAI_API_KEY` (moderation module).

| Target | What it does |
| --- | --- |
| `make` (`all`) | `env` + `up` |
| `make env` | `scripts/init-env.sh`: when `.env` is missing, copies `.env.example` and fills the empty secrets (`JWT_SECRET`, `INTERNAL_API_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`) with `openssl rand -hex 32`. When `.env` exists, it appends each key of `.env.example` that `.env` lacks: a generated value for those five secrets, the example value for the rest (an existing `.env` from before INF-09 thus gets `GRAFANA_ADMIN_PASSWORD`). It never changes a value already in `.env` and prints key names only, never values. A key counts as present also when its line is indented or written `export KEY=…` (compose reads both forms), so such a line gets no second copy (since the INF-09 review) |
| `make up` | `env`, then `infra/proxy/scripts/gen-cert.sh` (the proxy exits without a certificate), then `docker compose up -d --build --wait`, which returns once every long-running service is healthy and `minio-init` has exited 0 (see Images, health checks and logs) |
| `make down` | stops and removes the containers, keeps volumes |
| `make logs` | last 100 lines of every service, then follows; `make logs s=api` for one service |
| `make test` | starts `db`, `redis-test` (profile `test`) and `minio` if needed and creates the test database when it is missing (see below); backend `ruff` + `pytest` in a throwaway `api-test` container (the `test` stage of the api image: runtime plus `requirements-dev.txt`, same non-root user; code mounted read-only), with `DATABASE_URL` set to `TEST_DATABASE_URL` as in CI; fails if any backend test is skipped, as CI; frontend lint, format check, type check and `vitest` in the build stage of its image. Leaves `db`, `redis-test` and `minio` running; `make down` and `make fclean` remove `redis-test` too (`--profile '*'`) |
| `make https-check` | smoke test of the routes of the one HTTPS origin against the running stack (see One origin over HTTPS) |
| `make images-check` | fails when a compose image, a Dockerfile `FROM` or a workflow image (`.github/workflows/`) is not pinned as `name:tag@sha256:…` or uses `latest`, naming each one; needs no running stack (see Images, health checks and logs) |
| `make files-check` | smoke test of `/files` against the running stack, ends with a Chrome console snippet (see File storage over HTTPS) |
| `make mail-check` | sign-up email end to end through the proxy against the running stack (see Email without a paid service) |
| `make metrics-check` | every Prometheus target up, one real series per source, retention 30d and 1GB, against the running stack (see M12 under Infra modules) |
| `make grafana-check` | Grafana through the proxy: login, security settings (public dashboards and snapshots off among them), the Prometheus datasource healthy, both dashboards provisioned with data in every panel (dashboard variables at their saved value), deletion refused, Grafana Live over WebSocket, against the running stack (see M12 under Infra modules) |
| `make fclean` | removes containers, volumes, the images built here and the certificate; **keeps `.env`**, which holds the hand-added `OPENAI_API_KEY` and the database password that matches the next volume |
| `make re` | `fclean` + `all` |

`down`, `logs` and `fclean` use `--profile '*'`, so they also reach services that are off by default (`worker`).

**Test database.** The backend tests delete what they find, so they run only on `POSTGRES_TEST_DB` (`wozu_test`), never on the app database `POSTGRES_DB`. `infra/db/create-test-db.sh` creates it, owned by `POSTGRES_USER`, with PostGIS (the schema has a `geography` column). It runs in the `db` container from two places: the image runs it once when the `db-data` volume is new (mounted as the single file `/docker-entrypoint-initdb.d/20-create-test-db.sh`, after the image's own `10_postgis.sh`), and `make test` runs it on every call (`docker compose exec`), so a volume created before the script gets the database too. It is idempotent, reads the names from the container environment, connects over the local socket (no password) and refuses a name that equals `POSTGRES_DB` or lacks `test` (the fixtures skip such a database). The tables come from the fixtures, which run `alembic` on `TEST_DATABASE_URL`.

**Test Redis.** The tests get their own Redis server, `redis-test` (profile `test`), never the site's `redis`: database numbers separate only keys, while pub/sub channels and `CLIENT KILL` are server-wide, so with database 1 of `redis` the tests sent their events to open `/ws` sockets, closed every listening connection of the site and failed on the extra subscriber (found by Khalil on #37). `make test` starts `redis-test` and passes `TEST_REDIS_URL=redis://redis-test:6379/0` and `REDIS_URL=redis://redis-test:6379/0` to the pytest run only (`-e` in the Makefile); `REDIS_URL` too, because `realtime/connection_manager.py` reads it when the conversation tests publish. The run uses `--no-deps`, so it does not start the api's own dependencies (`redis`, `minio-init`). This way the 20 WebSocket tests in `tests/test_realtime.py` run, as in CI, instead of being skipped, and the media tests (`tests/test_media.py`) empty the `celery` queue of `redis-test`, never the app's. Neither URL is in the api's runtime environment. CI matches: the backend job has its own `redis:7-alpine` service container, and `REDIS_URL`, unset there, falls back to that same server.

**Test MinIO.** The media and picture tests (BE-07, BE-08: 187 tests in `tests/test_media.py` and `tests/test_pictures.py`) run against the dev MinIO, each in its own bucket: `media-test` and `pictures-test`. They create the bucket when it is missing and empty it before each test; they never touch the app bucket `MINIO_BUCKET` (`files`) and never delete a bucket, so the two empty buckets stay between runs. `make test` passes `TEST_MINIO_ENDPOINT=minio:9000` with `-e`; inside the throwaway container `TEST_MINIO_ACCESS_KEY` and `TEST_MINIO_SECRET_KEY` are set from the container's own `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` (`$$` in the Makefile), so the keys are never on a host command line, in the make output or in Git.

**No skipped backend test.** As in the backend CI job, pytest writes a JUnit report inside the throwaway container and `make test` fails when its `skipped` count is not 0 (`N tests skipped; make test must run every backend test, as CI`); `-rs` prints the reason of each skip, e.g. `TEST_REDIS_URL is not set`. A missing service or `TEST_*` variable therefore fails `make test` instead of passing with fewer tests.

**`.env.example` additions to the reference file** (every variable in `.env.example` has a comment there)

| Variable | Example | Used by |
| --- | --- | --- |
| `DOMAIN` | `localhost` | proxy (`server_name`), links |
| `HTTPS_PORT` / `HTTP_PORT` | `443` / `80` | host ports of the proxy |
| `FRONTEND_BASE_URL` | `https://localhost` | email links; Grafana root URL (`${FRONTEND_BASE_URL}/grafana/`) |
| `JWT_SECRET` | generated | api (BE-03 reads this name; the card said `SECRET_KEY`) |
| `INTERNAL_API_KEY` | generated | api, `/_internal/*` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `wozu` / generated / `wozu` | db; compose builds `DATABASE_URL` for api and worker from them |
| `POSTGRES_TEST_DB` | `wozu_test` | db (`infra/db/create-test-db.sh` creates it on a new volume, `make test` when it is missing); compose builds `TEST_DATABASE_URL` for the tests from it |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | `wozu` / generated | minio, minio-init; api and worker as `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` until INF-13 |
| `MINIO_EXTERNAL_ENDPOINT` | `https://localhost` | api, worker: presigned URLs (with the port when `HTTPS_PORT` is not 443) |
| `MINIO_BUCKET` | `files` | api, worker, minio-init; must match the `/files` route |
| `MINIO_REGION` | `us-east-1` | api, worker: signing without a region lookup |
| `SMTP_HOST` / `SMTP_PORT` / `MAIL_FROM` | `mailpit` / `1025` / `no-reply@wozu.local` | api |
| `GRAFANA_ADMIN_PASSWORD` | generated | grafana: password of the user `admin`, set when the `grafana-data` volume is new; compose stops with an error when it is missing |
| `OPENAI_API_KEY` | empty, filled by hand | worker |
| `MODERATION_FAIL_OPEN` | `false` on defense day | worker |

Compose passes each service only the variables it needs (`environment:`), not the whole `.env`. Addresses inside the Docker network are written in `docker-compose.yml`, not `.env`: the `db` host in `DATABASE_URL`, `MINIO_ENDPOINT=minio:9000`, and `REDIS_URL=redis://redis:6379/0` for api and worker (`x-backend-env`). The backend's `settings.redis_url` defaults to the same value, but `realtime/connection_manager.py` reads `REDIS_URL` and falls back to `localhost`; inside a container that is the container itself, so without the variable a published event was lost without an error and never reached the other user's `/ws` (found by Khalil in #24).

**Rules:** `.env` and `scripts/*.local` in `.gitignore`; nothing secret in `docker-compose.yml`, images or logs; with the Vault module, secrets move from `.env` to Vault and `.env` keeps only the Vault address and AppRole credentials.

## Infra modules

Each checklist mirrors the subject's bullets for that module; every box must be demonstrable live at the defense, or the module scores 0.

**M12 — Monitoring with Prometheus + Grafana (Major, 2, core)**

- [x] Prometheus scrapes the API `/metrics` (via `prometheus-fastapi-instrumentator`; backend card BE-30), Postgres, Redis and container exporters (INF-08)
- [x] Exporters and integrations configured in `prometheus.yml`, committed (`infra/prometheus/prometheus.yml`, INF-08)
- [x] Custom Grafana dashboards provisioned from JSON files: API request rate, error rate, p95 latency (all routes) and mean latency per route, WebSocket connections, DB connections, Redis memory, container CPU / RAM of this compose project (`infra/grafana/dashboards/`, INF-09)
- [ ] Alerting rules: target down, API 5xx rate above a threshold, p95 latency above a threshold, disk almost full; show one alert firing live (stop a container)
- [x] Grafana secured: admin password from `.env`, anonymous access off, served only over HTTPS at `/grafana` (INF-09)

**Prometheus and exporters (INF-08, 2026-11-15).** Prometheus works by pull: every 15 s (`scrape_interval`, `evaluation_interval` 15 s for the INF-10 rules) it sends `GET /metrics` to each target listed in `infra/prometheus/prometheus.yml` and stores the answer in its time-series database. Nothing pushes to it. An exporter is a small server that reads a system which has no `/metrics` of its own (PostgreSQL, Redis, the container runtime) and serves the figures in the Prometheus text format.

| Job | Target (inside the Docker network) | Source | Example series |
| --- | --- | --- | --- |
| `prometheus` | `localhost:9090` | Prometheus itself | `prometheus_tsdb_head_series` |
| `api` | `api:8000/metrics` | FastAPI, `prometheus-fastapi-instrumentator` (BE-30, `backend/app/core/metrics.py`); at the root of the app, no key | `http_requests_total`, `http_request_duration_seconds` (per route, buckets 0.1 / 0.5 / 1 s), `http_request_duration_highr_seconds` (all routes, buckets from 10 ms), `ws_connections` |
| `postgres` | `postgres-exporter:9187` | `prometheuscommunity/postgres-exporter` | `pg_up`, `pg_stat_database_numbackends` |
| `redis` | `redis-exporter:9121` | `oliver006/redis_exporter` | `redis_up`, `redis_memory_used_bytes` |
| `cadvisor` | `cadvisor:8080` | cAdvisor | `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`, by `container_label_com_docker_compose_project` and `container_label_com_docker_compose_service` |

**No exposure.** None of the five publishes a host port and the proxy has no route to them, so Prometheus, the exporters and the API's `/metrics` are reachable only from the Docker network. The proxy keeps answering 404 for `/metrics*` and `/api/metrics*` (One origin over HTTPS); `make https-check` checks it. Grafana (INF-09) is the only way in, at `/grafana` with a login. For a raw query without Grafana, ask the API from inside the container: `docker compose exec -T prometheus wget -qO- 'http://127.0.0.1:9090/api/v1/query?query=up'`.

**Retention (PO decision 2026-11-12).** Logs and metrics are kept at most 30 days; this replaces the card's "e.g. 7 days". Prometheus runs with `--storage.tsdb.retention.time=30d` and `--storage.tsdb.retention.size=1GB` and deletes the oldest blocks when either limit is reached. Data lives in the named volume `prometheus-data`, so it survives `make down` and goes with `make fclean`. Size: on 2026-11-15 one scrape round is about 4,150 samples (postgres 2,236, prometheus 891, cadvisor 512, redis 373, api 133), about 24 million samples a day; at the usual 1 to 2 bytes per stored sample that is about 35 MB a day, so on a stack that runs day and night the 1 GB cap applies after about four weeks, and on a laptop that runs only part of the day the 30 days apply first. `prometheus_tsdb_storage_blocks_bytes` shows the real figure after a few days. Prometheus flags the retention as decided. The Privacy Policy says the same since #38 (DOC-01/02 follow-up): server logs and service metrics are kept at most 30 days (sections 2 and 6). INF-08 does not change the legal texts.

**Personal data.** The API's labels are the route template, the method and the status: `handler="/api/jobs/{job_id}"`, never `/api/jobs/987654`; a path that matches no route is counted as `handler="none"` (checked on 2026-11-15). The exporters report counts, sizes and states, no rows or keys. cAdvisor labels a series with the container's name, image, compose project and compose service only (`--store_container_labels=false`), so no environment variable reaches a label.

**Credentials.** `postgres-exporter` logs in with the app's `POSTGRES_USER` / `POSTGRES_PASSWORD` from `.env` (compose interpolation into `DATA_SOURCE_URI`, `DATA_SOURCE_USER`, `DATA_SOURCE_PASS`; separate variables, so a password needs no URL encoding). No new secret, nothing in Git. INF-13 moves them to Vault; a dedicated role with `pg_monitor` only would also give the exporter least privilege then. `redis` has no password, so `redis-exporter` needs none.

**cAdvisor.** Not privileged. It runs as root inside its container (the image's default), with these read-only mounts:

| Mount | Why |
| --- | --- |
| `/var/run/docker.sock` | Lists the containers and reads their names and labels (the compose service) |
| `/run/containerd/containerd.sock` | cAdvisor 0.60's Docker support asks containerd for each container's details; without it, "Registration of the docker container factory failed" and no container shows up |
| `/sys` | The cgroup counters: CPU and memory per container |
| `/var/lib/docker` | Each container's metadata on disk |

Left out: `/` (as `/rootfs`) and `/dev/disk`, which only the disk metrics need, and those are off. Also left out: `/var/run` as a whole, which upstream examples mount. On Docker Desktop for Mac that path is the Mac's own `/private/var/run` (macOS sockets, no Docker socket), while the four paths above resolve inside Docker Desktop's Linux VM; on the ubuntu CI runner they are the host's own. The socket mounts are `:ro`, but that only stops the file from being replaced: whoever can talk to the Docker or containerd socket controls the host. cAdvisor is therefore on the internal network only, with no port. Flags: `--docker_only=true` (no system cgroups), `--housekeeping_interval=30s` (stats every 30 s instead of every second), `--enable_metrics=cpu,memory` (INF-09 and INF-10 add groups such as network or disk if a panel or rule needs one), `--store_container_labels=false` and `--whitelisted_container_labels=com.docker.compose.project,com.docker.compose.service`: of all the container labels, only the compose project and service become Prometheus labels (`container_label_com_docker_compose_project="wozu"`, `container_label_com_docker_compose_service="api"`). The project label came with the INF-09 review: cAdvisor sees every container on the Docker host, other compose projects too (a second clone, another team's stack on the same laptop), and with the service label alone their `db` was added to this stack's `db`. The Grafana container panels filter on the project (see Grafana below). Checked on Docker Desktop 28.4 (Apple Silicon); the CI `stack` job checks the ubuntu runner on every run (`make metrics-check`). On Docker Desktop cAdvisor logs, at start, that `/etc/machine-id` and `/dev/kmsg` are missing; both are harmless (no machine ID label, no OOM events).

**Images** (latest stable release of each on 2026-11-15, pinned by the digest of the multi-arch index; `docker buildx imagetools inspect` lists linux/amd64 and linux/arm64 for each; `make images-check` covers them, 14 → 18 images; 19 with Grafana since INF-09):

| Service | Image |
| --- | --- |
| `prometheus` | `prom/prometheus:v3.16.0@sha256:e04987641b57704f408e31f6373ba4138ecf27cb4a165d24aabb6c38fddd0f06` |
| `postgres-exporter` | `prometheuscommunity/postgres-exporter:v0.20.1@sha256:ac5ec343104fae0e2d84a27bb8d69b38430a11910c5382cad85d478d2bab713e` (same index as on quay.io) |
| `redis-exporter` | `oliver006/redis_exporter:v1.97.0@sha256:f5f903fbe77571d455ede0453b084d6840bc62fc105efac001034421cab83b99` |
| `cadvisor` | `ghcr.io/google/cadvisor:v0.60.6@sha256:b8e7d1093144fd088f425ff003d75a4aa405de075db78dae3bc563730b1bd07a`. ghcr.io, not gcr.io: `gcr.io/cadvisor/cadvisor` has no release after v0.55.1, and the v0.56+ releases are published on ghcr.io only |

**Resources** (`docker stats --no-stream`, Docker Desktop on Apple Silicon, 2026-11-15, a few minutes after start, idle stack): prometheus 62 MiB, 1.4 % CPU; postgres-exporter 14 MiB; redis-exporter 17 MiB; cadvisor 20 MiB, 1.6 % CPU. About 115 MiB together; Prometheus grows with the stored data, which the 1 GB cap bounds on disk. Image sizes: prometheus 364 MB, cadvisor 92 MB, postgres-exporter 34 MB, redis-exporter 15 MB.

**Log volume.** The API logs every request, `GET /metrics` included: one line per scrape, 4 a minute (about 1 MB a day), within the 30 MB rotation of `x-logging`. Leaving `/metrics` out of the request log would be a backend change (BE-30 / `app/core/request_id.py`), not part of INF-08.

**Check:** `make metrics-check` (`infra/prometheus/smoke-test.sh`) against the running stack. Prometheus has no host port, so the script queries it inside its container (`docker compose exec -T prometheus wget -qO- http://127.0.0.1:9090/api/v1/...`) and parses the JSON on the host with `python3`. It requires: each of the jobs `prometheus`, `api`, `postgres`, `redis`, `cadvisor` has a target and every active target has health `up`, from a scrape made after the check started (health is the result of the last scrape, up to 15 s old: without this rule a target stopped a few seconds before would still pass; "after" is measured by Prometheus's own `time()`); `pg_up == 1`; `redis_up == 1`; a CPU and a memory series of the `api` container (cAdvisor, selected by the compose service label); `sum(http_requests_total{job="api"}) > 0`; and the retention flags in `/api/v1/status/flags` equal to 30d and 1GB (compared as values: Prometheus prints `1GB` back as `1GiB` and `7d` as `1w`). A fresh stack needs a scrape or two, so it retries for up to 60 s (a healthy stack passes after one scrape interval, about 15–20 s), then prints one `ok` / `FAIL` line per check and exits 1 if one failed. The CI `stack` job runs it after `make images-check`. To see it fail: `docker compose stop redis-exporter` makes `target redis` and `redis_up` FAIL after the 60 s; `docker compose start redis-exporter` brings them back.

**Grafana (INF-09, 2026-11-15).** Grafana reads the series Prometheus stores and draws them as dashboards. It is the only way into the monitoring data from a browser.

**URL and login.** `https://localhost/grafana/` (behind the proxy, no host port). User `admin`, password `GRAFANA_ADMIN_PASSWORD` from `.env`. `make env` generates the password (`openssl rand -hex 32`), and it is never printed or committed. To read it on the machine that runs the stack: `docker compose exec grafana printenv GF_SECURITY_ADMIN_PASSWORD`. Compose refuses to start without the variable (`GRAFANA_ADMIN_PASSWORD missing in .env, run make env`).

Grafana stores the password in its database when the `grafana-data` volume is new, so changing the value in `.env` later does not change it. To change it on a running stack, either:

- reset it: `docker compose exec grafana grafana cli admin reset-admin-password '<new>'`, then set the same value in `.env`;
- or start from a new volume (`make fclean`, which also wipes the other volumes).

**Root URL.** `GF_SERVER_ROOT_URL=${FRONTEND_BASE_URL}/grafana/` and `GF_SERVER_SERVE_FROM_SUB_PATH=true`. Grafana serves under `/grafana/` itself, so the proxy passes the URI unchanged. The links, redirects and the `appUrl` of the page all stay on the public origin. With `HTTPS_PORT=18443` and `FRONTEND_BASE_URL=https://localhost:18443`, the login redirects to `https://localhost:18443/grafana/` (tested on 2026-11-15).

**Grafana Live** is Grafana's WebSocket at `/grafana/api/live/ws`. It gets the `Upgrade` / `Connection` headers and HTTP/1.1 that the proxy's server block sets for every location. Setting them again inside `location /grafana/` would drop the server-level `Host` and `X-Forwarded-*` headers, because nginx inherits `proxy_set_header` only when a block sets none.

**Security settings** (environment of the `grafana` service in `docker-compose.yml`; `make grafana-check` reads them back from `/api/admin/settings`):

| Setting | Value | Why |
| --- | --- | --- |
| `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` | `admin` / from `.env` | One account; the password is not in Git |
| `GF_AUTH_ANONYMOUS_ENABLED` | `false` | Without a login, every page redirects to `/grafana/login` and the API answers 401 |
| `GF_USERS_ALLOW_SIGN_UP` / `GF_USERS_ALLOW_ORG_CREATE` | `false` / `false` | No one can create an account or an organisation (`POST /grafana/api/user/signup` → 401 "User signup is disabled") |
| `GF_SECURITY_COOKIE_SECURE` | `true` | The session cookie `grafana_session` is sent over HTTPS only |
| `GF_SECURITY_DISABLE_GRAVATAR` | `true` | No avatar requests to gravatar.com |
| `GF_ANALYTICS_REPORTING_ENABLED`, `GF_ANALYTICS_CHECK_FOR_UPDATES`, `GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES`, `GF_NEWS_NEWS_FEED_ENABLED` | `false` | No usage reports, update checks or news feed from the defense machine |
| `GF_PLUGINS_PREINSTALL_DISABLED` | `true` | Grafana 13 otherwise downloads about ten plugins from grafana.com at first start. The built-in Prometheus datasource is all the dashboards need, so `/var/lib/grafana/plugins` stays empty |
| `GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED`, `GF_PLUGINS_PLUGIN_ADMIN_ENABLED` | `true`, `false` | The plugin signing key is not fetched from grafana.com (Grafana uses its built-in one), and the plugin catalogue page is off |
| `GF_PUBLIC_DASHBOARDS_ENABLED` | `false` | Admin cannot give a dashboard a public link that works without a login; the API for it answers 404 (since the INF-09 review) |
| `GF_SNAPSHOTS_ENABLED` | `false` | No snapshots at all; creating one answers 403 "Dashboard Snapshots are disabled" (PO decision, byul-byul, 2026-11-16; see below) |
| `GF_SNAPSHOTS_EXTERNAL_ENABLED` | `false` | The share option "Publish to snapshots.raintank.io" is gone, the last way the UI could send data out to grafana.com (since the INF-09 review) |
| brute-force protection | on (the default, not disabled) | 5 failed logins for one username within 5 minutes lock that username for 5 minutes |

**Snapshots** are off, local ones too (PO decision, byul-byul, 2026-11-16). A snapshot is a copy of a dashboard with its data, stored in Grafana's own database. Whoever has its link (a random 32-character key) can open it without a login: tested on 2026-11-16 with snapshots still on, `GET /grafana/api/snapshots/<key>` and the snapshot page answered 200 without a session, although `[snapshots] public_mode` is `false`. The project does not need snapshots, so `GF_SNAPSHOTS_ENABLED: "false"` removes them: `POST /grafana/api/snapshots` answers 403 "Dashboard Snapshots are disabled".

**Lockout behaviour.** Grafana counts failed logins per username; its per-IP protection is off by default (`disable_ip_address_login_protection = true`). A locked login answers exactly like a wrong password: 401 "Invalid username or password". A successful login does not reset the count. To unlock, wait 5 minutes. `make grafana-check` sends its wrong password for a user that does not exist (`grafana-check-nobody`), never for `admin`, so any number of runs leaves `admin` unlocked. Six runs in a row followed by an `admin` login were tested on 2026-11-15.

**Provisioning.** Nothing is clicked together in the UI. Three read-only mounts from `infra/grafana/`:

| File | Provisions |
| --- | --- |
| `provisioning/datasources/prometheus.yml` | Datasource `Prometheus`, uid `prometheus`, `http://prometheus:9090` inside the Docker network, default, `editable: false` |
| `provisioning/dashboards/wozu.yml` | Folder `WOZU`, which loads every JSON file of `dashboards/`. It rescans every 10 s, so an edited file shows without a restart. `disableDeletion: true` and `allowUiUpdates: false`: a dashboard cannot be deleted, and a change saved in the UI is refused. The file in Git is the only source |
| `dashboards/api.json`, `dashboards/infrastructure.json` | The two dashboards below |

Both dashboards have the same settings:

- a fixed uid, so links stay stable after `make re`;
- the datasource referred to by uid (`prometheus`);
- refresh every 30 s, range the last hour;
- `editable: false`;
- tag `wozu` and a link to each other.

The description of each panel (the ⓘ next to its title) explains the query in plain words.

| Dashboard (uid) | Panel | Query |
| --- | --- | --- |
| WOZU API (`wozu-api`) | Request rate by handler | `sum by (handler) (rate(http_requests_total{job="api"}[5m]))` |
| | Open WebSocket connections | `sum(ws_connections{job="api"})` |
| | Error rate (share of requests) | 5xx and 4xx share: `(sum(rate(http_requests_total{job="api", status=~"5.."}[5m])) or vector(0)) / sum(rate(http_requests_total{job="api"}[5m]))` and the same for `4..` |
| | p95 latency (all routes) | `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_highr_seconds_bucket{job="api"}[5m])))` |
| | Mean latency by handler | `sum by (handler) (rate(http_request_duration_seconds_sum{job="api"}[5m])) / sum by (handler) (rate(http_request_duration_seconds_count{job="api"}[5m]))` |
| WOZU Infrastructure (`wozu-infra`) | Target health | `up`, one box per scrape job, green UP / red DOWN |
| | DB connections | `sum(pg_stat_database_numbackends{job="postgres"})` against `pg_settings_max_connections` |
| | Redis memory | `redis_memory_used_bytes{job="redis"}` |
| | Container CPU by compose service | `sum by (container_label_com_docker_compose_service) (rate(container_cpu_usage_seconds_total{container_label_com_docker_compose_project="$project", container_label_com_docker_compose_service!=""}[5m]))` |
| | Container memory by compose service | `sum by (container_label_com_docker_compose_service) (container_memory_working_set_bytes{container_label_com_docker_compose_project="$project", container_label_com_docker_compose_service!=""})` |

**Latency: why no p95 per route.** The API has two latency histograms (`prometheus-fastapi-instrumentator` defaults, BE-30). `http_request_duration_seconds` has a route label (`handler`) but only the buckets 0.1, 0.5 and 1 s. `histogram_quantile` interpolates inside the bucket where the 95th request falls, so every route faster than 100 ms reads 0.95 × 100 ms = 95 ms. That is what the first "p95 latency by handler" panel showed for every route; Khalil found it in the review. `http_request_duration_highr_seconds` has buckets from 10 ms (10, 25, 50, 75, 100, 250 ms, …) but no route label, so its p95 is for all routes together. Per route, the dashboard shows the mean (`_sum / _count`), which is exact whatever the buckets but hides slow outliers. Measured on 2026-11-16 for `/api/health` (the only route with traffic on an idle stack): old panel 95.0 ms, new p95 of all routes 19 ms, mean 2.5 ms. The p95 lands at 19 ms because about one request in eight took between 10 and 25 ms, and the value is interpolated inside that bucket. A p95 per route would need finer buckets on the per-route histogram in `backend/app/core/metrics.py`, a backend change outside INF-09.

**Compose project variable.** The infrastructure dashboard has one variable, `project` (label "Compose project", the dropdown at the top). Its values are `label_values(container_memory_working_set_bytes, container_label_com_docker_compose_project)`, every compose project cAdvisor sees. Its default is `wozu` (`name: wozu` at the top of `docker-compose.yml`). Both container panels filter on `container_label_com_docker_compose_project="$project"`. Without the filter, another compose project on the same Docker host adds its containers to the same lines. Tested on 2026-11-16 with a throwaway container labelled `com.docker.compose.project=inf09-other`, `com.docker.compose.service=db`: the old memory query's `db` line summed both containers, the new one only this stack's `db`. CI and a clean defense machine have one project only, so they never showed it.

The default is fixed in the dashboard JSON, so it only matches a stack started under the name from `docker-compose.yml`. A stack started under another project name (`COMPOSE_PROJECT_NAME=… make`, or `docker compose -p …`) gets container labels with that name. In the browser, the dropdown then falls back to the first project Prometheus offers. Whoever runs such a stack picks their own project in the dropdown. `make grafana-check` FAILs on it by design ("variable project: current wozu, offered …", and both container panels with 0 series): the check tests what the browser opens with, and that would be another project, or none.

**Check:** `make grafana-check` (`infra/grafana/smoke-test.sh`) runs against the running stack, over HTTPS from the host through the proxy, with the proxy certificate as the trusted CA. It reads the root URL and the admin password from the `grafana` container (`docker compose exec -T grafana printenv`) into a private temporary file; the password is never printed or put on a command line. Then it checks, with one `ok` / `FAIL` line each:

1. Entry and login:
   - `/grafana/` without a login redirects to `/grafana/login`;
   - the login page's `appUrl` is the public origin plus `/grafana/`;
   - `POST /grafana/login` as `admin` works, stays on the origin and sets a `Secure` session cookie.
2. `/api/health` reports the database as ok.
3. Access and settings:
   - anonymous API access gets 401;
   - sign-up is disabled;
   - the 14 settings of the table above are read back from `/api/admin/settings` (`public_dashboards.enabled`, `snapshots.enabled` and `snapshots.external_enabled` among them);
   - the public-dashboard API (`POST /api/dashboards/uid/wozu-api/public-dashboards`) answers 404 with Grafana's JSON `{"message": "Not found"}`; if it ever makes a public link, the check removes it again at once and fails. Grafana has no message of its own for this (any route it does not have answers the same), so the check can only tell Grafana's 404 from one the proxy writes (an HTML page);
   - `POST /api/snapshots` with a real dashboard answers 403 with Grafana's own message "Dashboard Snapshots are disabled"; a 403 with any other body fails with a hint that the WAF may have answered (see the INF-11 note below); if it ever makes a snapshot, the check deletes it again with its `deleteKey` and fails;
   - `/api/snapshot/shared-options` reports `externalEnabled: false`;
   - the plugins directory is empty.
4. The datasource has uid `prometheus`, type, URL, default and read-only as provisioned, and its health check passes.
5. Each dashboard is in folder `WOZU` and provisioned, and every panel query returns data (`/api/ds/query`). Dashboard variables are replaced by their saved current value first, the value the browser opens with: `$project` becomes `wozu`. That value must be one the variable's own query offers (asked through Grafana's datasource resource API, as the dropdown does). Otherwise the browser would fall back to the first project in the list, and the check would test queries nobody sees.
6. `DELETE` of a dashboard is refused and the dashboard is still there.
7. Grafana Live: the WebSocket handshake through the proxy answers 101.
8. Last, a wrong password is refused with 401, for the non-existent user `grafana-check-nobody` so that `admin` is never locked.

A fresh stack needs a scrape or two before every panel has data, so it retries every 5 s for up to 60 s (`GRAFANA_CHECK_WAIT` changes the limit). It exits 1 if a check failed. The CI `stack` job runs it after `make metrics-check`.

To see it fail:

- `url: http://prometheus:9999` in `provisioning/datasources/prometheus.yml` plus `docker compose restart grafana` makes the datasource and every panel FAIL ("connection refused").
- `GF_AUTH_ANONYMOUS_ENABLED: "true"` in compose plus `docker compose up -d grafana` makes the login redirect, anonymous access and the setting FAIL.
- `GF_PUBLIC_DASHBOARDS_ENABLED: "true"` in compose plus `docker compose up -d grafana` makes the settings line and the public-dashboard line FAIL (the public link the check makes is removed again).
- `GF_SNAPSHOTS_ENABLED: "true"` in compose plus `docker compose up -d grafana` makes the settings line and the snapshot line FAIL (the snapshot the check makes is deleted again).
- `"current": { "text": "nobody", "value": "nobody" }` for the `project` variable in `dashboards/infrastructure.json` (no restart, Grafana rescans in 10 s) makes the variable line and both container panels FAIL.

Undo each with `git checkout` and the same command.

**Image:** `grafana/grafana:13.3.1@sha256:0615ec4fbd4072004b7d86b46ded63013a74b7d6eb1119273dd89e8fa25c13cf`. It is the OSS image (not `grafana-enterprise`), the latest stable release on 2026-11-15, and its multi-arch index lists linux/amd64 and linux/arm64. Grafana logs at start that `[security] x_xss_protection` is deprecated. Compose does not set it, so the warning comes from Grafana's own defaults; it is harmless.

**Resources** (`docker stats --no-stream`, Docker Desktop on Apple Silicon, 2026-11-15, idle): about 320 MiB of memory and under 1 % CPU. The image takes about 1.9 GB on disk.

For INF-10, from the INF-09 review (Khalil, 2026-11-15): the p95 latency alert must use `http_request_duration_highr_seconds_bucket`, as the "p95 latency (all routes)" panel does. On `http_request_duration_seconds_bucket` the p95 never reads below 95 ms (its first bucket ends at 100 ms, and every route under 100 ms reads 95 ms), so a threshold below 95 ms would always fire, one between 95 and 100 ms never on such a route, and one above could fire late. See "Latency: why no p95 per route" above.

**M13 — WAF / ModSecurity (hardened) + HashiCorp Vault (Major, 2, buffer)**

- [ ] Front proxy runs ModSecurity v3 with OWASP Core Rule Set, `SecRuleEngine On` (blocking, not detection only), paranoia level 2, tuned exclusions for our JSON API and WebSockets
- [ ] Demo: an SQL injection and an XSS probe return 403 and appear in the WAF audit log; normal app use triggers no false positives
- [ ] Vault in server mode (not dev mode) with file storage; init and unseal by a startup script; unseal keys kept out of Git
- [ ] API, worker and DB credentials, JWT secret, OpenAI and MinIO keys read from Vault (AppRole or Vault Agent rendering an env file); none left in `.env`
- [ ] Policies give each service read access only to its own path

For INF-11, from INF-04: presigned uploads must keep working once `MODSEC_RULE_ENGINE=On`. `PUT` stays in `ALLOWED_METHODS` (CRS rule 911100 scores it otherwise) and the upload content types in `ALLOWED_REQUEST_CONTENT_TYPE` (rule 920420); see "For INF-11" in [infra/proxy/README.md](../../infra/proxy/README.md). `/files` keeps its 60 MB body limit (`client_max_body_size 60m`) and `SecRequestBodyLimitAction ProcessPartial`. `make files-check` and the browser snippet must still pass with blocking on.

For INF-11, from the INF-09 review (Khalil, 2026-11-15, engine still `DetectionOnly`, no 403 in the proxy log): ModSecurity already scores Grafana traffic at the blocking thresholds. Rule 942100 (SQL injection) matches the PromQL of the "Open WebSocket connections" and "DB connections" panels on every refresh. Rule 911100 matches Grafana's `PATCH` calls (user storage, while browsing) and the `DELETE` in `make grafana-check`. Both score 5, the inbound blocking threshold. Rule 953100 scores 4, the outbound threshold, on the uncompressed login page that `make grafana-check` fetches. The snapshot `POST` of `make grafana-check` (`/grafana/api/snapshots`, a whole dashboard JSON as body) scores 10, rules 942100 and 932235 (seen again in the audit log on 2026-11-17); with blocking on, the WAF would answer it with its own 403 before Grafana does, which is why the check requires Grafana's message "Dashboard Snapshots are disabled" (INF-09 follow-up). With blocking on, `/grafana/` needs exclusions, or those panels, the UI's `PATCH` calls, the snapshot `POST` and `make grafana-check` break. Audit log volume: about 2.4 kB per open dashboard every 30 s, about 65 kB per `make grafana-check` run. `make grafana-check` must still pass with blocking on.

**M14 — Health checks, status page, backups, disaster recovery (Minor, 1, buffer)**

- [x] Health checks for every service in compose (the reference has them for API, DB, Redis, MinIO); INF-07, see Images, health checks and logs
- [ ] Public status page showing each component green / red, fed by `/api/health` (without internal details)
- [ ] Automated daily `pg_dump` and bucket mirror, 7 copies kept
- [ ] Restore runbook in `docs/disaster-recovery.md`, tested: drop the DB volume, restore, app works

**Mandatory (no points, but rejection if missing):** HTTPS everywhere, one-command start, `.env` handling, mail catcher, pinned images, no secrets in Git.

## CI

INF-06 (2026-11-12, updated 2026-11-13): one GitHub Actions workflow, `.github/workflows/ci.yml`, runs on every pull request, onto any branch, and on every push to `main`. It replaced `backend.yml` (Nader: BE-20; Khalil: BE-07, BE-06) and `frontend.yml` (Zayid: FE-01, FE-13, FE-04, FE-06); every job and step of both files is in it. It has no trigger-level `paths:` filter: a workflow that a path filter keeps from starting leaves its required check "Expected" forever, and the merge stays blocked. Instead a `changes` job reads the changed files, the jobs with nothing to check are skipped, and the `ci-ok` job sums up the result. `ci-ok` is the only required check on `main`. CI is not a module; it keeps `main` demo-ready and makes reviews visible in the Git history.

**Triggers.** `pull_request` has no branch filter: a stacked PR (one onto another PR's branch, such as #35 onto the branch of #34) gets the same CI as a PR onto `main`. The `changes` job compares the PR with its own base (`github.event.pull_request.base.sha`, the tip of whatever branch it targets), so a stacked PR is judged by its own files, not by its parent's. `push` runs on `main` only: a feature branch gets CI once its PR is open (drafts included).

| Job | Runs when the PR touches | Steps | Proves |
| --- | --- | --- | --- |
| `changes` | always | `git -c core.quotePath=false diff --no-renames --name-only <base>...<head>` (checkout with `fetch-depth: 0`); outputs `backend`, `frontend`, `stack`; the job summary lists the files. A push to `main` sets all three | Which jobs have work |
| `backend` | `backend/**`, `.github/workflows/**` | Service containers `imresamu/postgis:15-3.4@sha256:44d4…` and `redis:7.4.12-alpine@sha256:7f7d…` (see Image pins); MinIO (`pgsty/minio`, compose digest) started with `docker run`; `pip install -r requirements-dev.txt`, `ruff check`, `ruff format --check`, `pytest` with a JUnit report, a step that fails on any skipped test, `docker build --target runtime` (the stage compose ships for `api` and `worker`, not the `test` stage) | Lint, format and every backend test against real PostgreSQL + PostGIS, Redis and MinIO; the shipped image builds |
| `frontend` | `frontend/**`, `docs/legal/**` (`legal:check`), `.github/workflows/**` | `npm ci`, `npm run lint`, `format:check`, `i18n:check`, `legal:check`, `typecheck`, `npm test` (vitest), `npm run build`, `docker build --target preview` (the stage compose ships) | Lint, format, every translation key present in every locale, legal pages in sync with `docs/legal`, types, unit tests, production build |
| `auth-integration` | whatever runs `backend` or `frontend`: `backend/**`, `frontend/**`, `docs/legal/**`, `.github/workflows/**` | Service container `imresamu/postgis:15-3.4@sha256:44d4…` (database `wozu_auth_test`); `pip install -r backend/requirements-dev.txt`, `npm ci`; starts the real backend with `frontend/scripts/serve-auth-test-backend.py` (the team's app, migrations and auth on `127.0.0.1:8010`, outgoing email captured so the tests can follow the verification link), waits up to 60 s for `/api/health` (prints the backend log if it never answers), then `npx vitest run --config scripts/auth-backend.config.ts`. Timeout 10 min | The frontend's authentication flows work against the real API and database, not only against mocks; a change on either side that breaks the contract turns it red |
| `stack` | `infra/**`, `docker-compose.yml` and any `compose*.yml`, `Makefile`, `scripts/**`, `.env.example`, `backend/**`, `frontend/**`, `.github/workflows/**` | `make` on the fresh checkout (new `.env` from `.env.example`, new certificate, build, start, `--wait` until healthy), `docker compose config -q`, `make test`, `make files-check`, `make mail-check`, `make https-check`, `make images-check`, `make metrics-check`, `make grafana-check`; service logs on failure; `docker compose down -v` at the end (on the runner, not on a laptop). Timeout 30 min | The evaluator's path: one command from a clean clone to a healthy stack; every variable reference resolves; `/files`, `/mail` and the one HTTPS origin (`/`, `/api`, `/ws`, redirects, hidden internal routes) work through the proxy; every image is pinned; every Prometheus target is up, cAdvisor sees the api container on the ubuntu runner, retention is as decided; Grafana logs in through the proxy with its security settings, both dashboards show data in every panel |
| `ci-ok` | always (`if: always()`) | `needs` all five jobs; fails when one of them ended `failure` or `cancelled`; `skipped` counts as passed | The single required check |

**Path rules.** Three dots (`base...head`): the files the branch changed since it left its base, not what the base gained meanwhile. `--no-renames`: a moved file is listed under its old and its new path; with rename detection only the new path showed, so moving `infra/db/create-test-db.sh` into `docs/` ran no job although it breaks `make test` (now `stack` runs). `core.quotePath=false`: Git prints non-ASCII names as they are instead of quoting them (`"backend/tests/t\303\251st.py"`), so `^backend/` still matches (now `backend` runs). Khalil reported both in his #39 review; the same ranges from our history give the same jobs as before. A base sha missing from the clone fails `changes`, and `ci-ok` goes red.

**Image pins.** Every image a workflow pulls is pinned by tag and digest, with the same value as `docker-compose.yml` (see Images, health checks and logs): the `postgres` service containers of `backend` and `auth-integration` use the `db` image (`imresamu/postgis:15-3.4@sha256:44d4443d107a7750ea29a441dec0050cd7543178f011ae0620e4b572578e9300`), the `redis` service of `backend` uses the `redis` / `redis-test` image (`redis:7.4.12-alpine@sha256:7f7d30b7fdd09467bac58198a1f166dd69789d348d4fe859cccb20e0cf287fbe`), and the MinIO `docker run` uses the `minio` image. `make images-check` reads every `image:` (service containers, `container:`), `container: <ref>` and `uses: docker://<ref>` in `.github/workflows/*.yml` and fails with file and line (`FAIL  .github/workflows/ci.yml:100 image: redis:7.4.12-alpine (no @sha256 digest)`); the `stack` job runs it. The MinIO reference sits inside a `run:` script, which the check does not parse; it is kept equal to compose by hand. To bump an image, change compose and `ci.yml` in the same commit.

**Workflow settings.** `permissions: contents: read`; one run per branch (`concurrency: ci-<ref>`, a new push cancels the older run); only official actions (`actions/checkout`, `actions/setup-python`, `actions/setup-node`) at their current major tag; pip and npm caches; no secrets: the backend job uses throwaway `ci-only-*` values, and the `stack` job generates its `.env` as `make` does on any fresh clone.

**Branch protection on `main`** (target settings; Khalil applies them as repo admin, since byul-byul has write access only):

| Setting | Value | Why |
| --- | --- | --- |
| Require a pull request before merging | on, 1 approving review | Every change is reviewed and the review shows in the Git history |
| Require status checks to pass | on, check `ci-ok` only | The jobs behind it may be skipped; `ci-ok` always reports |
| Require branches to be up to date before merging | off | No rebase churn on every merge to `main`; CI on the push to `main` catches a bad combination |
| Do not allow bypassing the above settings (include administrators) | on | The rules apply to the admin too |
| Allow force pushes / Allow deletions | off | `main` history cannot be rewritten or removed |

Khalil applies the rule after #39 is merged and the push run on `main` is green (before that, `ci-ok` does not exist on `main`). He sends the required check as `"checks": [{"context": "ci-ok", "app_id": 15368}]`, not as `"contexts": ["ci-ok"]`: the API marks `contexts` as closing down, and `app_id` 15368 (GitHub Actions) means only a `ci-ok` reported by GitHub Actions satisfies the rule, not a status of the same name posted by another app or token. The PUT replaces the whole rule, so it carries the review requirement too:

```bash
gh api -X PUT repos/Khalil-QadDoura/ft_transcendence/branches/main/protection \
  -H "Accept: application/vnd.github+json" --input - <<'JSON'
{
  "required_status_checks": { "strict": false, "checks": [{ "context": "ci-ok", "app_id": 15368 }] },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 1 },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
gh api repos/Khalil-QadDoura/ft_transcendence/branches/main/protection --jq '{checks: .required_status_checks.checks, reviews: .required_pull_request_reviews.required_approving_review_count, admins: .enforce_admins.enabled, force: .allow_force_pushes.enabled}'
```

Expected: `{"admins":true,"checks":[{"app_id":15368,"context":"ci-ok"}],"force":false,"reviews":1}`.

**How to read a red CI.** The PR's checks list shows which job failed; `ci-ok` is red whenever one of the others is, so open the other red job. In the job log, the red step names the command (the same as the local one: `ruff check`, `pytest`, `npm run lint`, `npm run i18n:check`, `make test`, …). The `changes` job's summary lists the changed files and which jobs ran. For `auth-integration`, a backend that never answers `/api/health` prints its log in the same step. For `stack`, the "Service logs" step prints `docker compose ps -a` and the last 300 lines of every service. A `skipped` job is not a failure: the PR does not touch its paths. To reproduce locally: `make test` runs the lint, format, type and test commands of the `backend` and `frontend` jobs and fails on any skipped backend test, as the `backend` job does; `npm run i18n:check` and `npm run legal:check` in `frontend/` are the two frontend checks `make test` leaves out; the `stack` job is `make`, `make test`, `make files-check`, `make mail-check`, `make https-check`, `make images-check`, `make metrics-check`, `make grafana-check`. `auth-integration` has no make target: it needs a loopback PostgreSQL test database in `TEST_DATABASE_URL` and runs the commands of its step.

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
