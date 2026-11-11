# ft\_transcendence — Infrastructure

Oct 27, 2026 · updated Nov 11, 2026 · @byul-byul

## TL;DR

Infra owns four mandatory items and five module points. The reference already has a working compose stack (Caddy, API, Celery worker, Postgres + PostGIS, Redis, MinIO); what is missing is the frontend container, HTTPS for file storage, a mail catcher and everything for the modules.

- **Mandatory:** one command starts everything; every browser connection is HTTPS; `.env` stays out of Git with a complete `.env.example`; the evaluator can sign up without a paid email service.
- **Modules:** Prometheus + Grafana (Major, 2, core); WAF / ModSecurity + Vault (Major, 2, buffer); health check, status page and backups (Minor, 1, buffer).
- **Front proxy decided (2026-11-04, INF-01):** nginx + ModSecurity v3 + OWASP Core Rule Set is the only front door instead of Caddy. Configuration: [infra/proxy/](../../infra/proxy/README.md).
- **File storage decided (2026-11-09, INF-04):** MinIO on the same origin at `/files`, private bucket `files` created by the one-shot `minio-init`, uploads and video reads through presigned URLs; see File storage over HTTPS.
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
| `redis` | `redis:7-alpine` | Pub/sub, queues, rate limits, Celery broker; api and worker use database 0 (`REDIS_URL`), the tests database 1 (`TEST_REDIS_URL`) | no | In compose, `redis-cli ping` health check |
| `minio` | `pgsty/minio:RELEASE.2026-08-04T00-00-00Z`, by digest (the official `minio/minio` and `minio/mc` images left Docker Hub on 2025-10-23) | Object storage for videos, avatars, logos | no, console included (proxied at `/files`) | In compose |
| `minio-init` | Same image as `minio`, which ships `mc` | One-shot: create bucket `files`, set its anonymous policy, exit 0 | no | In compose (INF-04); `api` starts after it completes |
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
| `/` | `frontend:80` | The frontend container does the SPA fallback to `index.html` for client routes; a missing `/assets/*` file is a 404, not `index.html` |
| `/api/*` | `api:8000` | FastAPI includes all routers under the `/api` prefix; the proxy does not strip paths |
| `/ws`, `/ws/game` | `api:8000` | WebSocket upgrade: HTTP/1.1, `Upgrade` and `Connection` headers, long read timeout |
| `/files/*` | `minio:9000` | Bucket `files`; URI and Host header passed through unchanged so presigned signatures match; 60 MB body limit |
| `/grafana/*` | `grafana:3000` | `GF_SERVER_ROOT_URL=https://localhost/grafana/`, `serve_from_sub_path=true`, login required |
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
| external | `MINIO_EXTERNAL_ENDPOINT` + `MINIO_REGION`, `secure=True` | Signing only: `presigned_put_object` (15 min), `presigned_get_object` (5 min). It never sends a request |

**Bucket init.** The one-shot `minio-init` service runs `infra/minio/init-bucket.sh` on every `make`:

1. Waits for MinIO with `mc ready` under a 60-second `timeout`; exits 1 if MinIO never comes up.
2. Creates the bucket with `mc mb --ignore-existing` when it is missing, else logs "already exists".
3. Replaces the anonymous policy with `mc anonymous set-json`, prints it and exits 0.

- **Image:** the `minio` server image itself, `pgsty/minio:RELEASE.2026-08-04T00-00-00Z@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372`, defined once in compose (`x-minio-image`). It ships `/usr/bin/mc` of the same release (checked with `mc --version`) for amd64 and arm64, so there is one image to pin and bump instead of two, and no `minio/*` or `pgsty/mc` image.
- **Credentials** reach `mc` only through `MC_HOST_wozu` in the container environment: never on a command line, in a config file or in the log. They must be URL-safe; `init-env.sh` generates hex.
- **Restart and `make`:** `restart: "no"`. `api` depends on it with `condition: service_completed_successfully`. The API hands out URLs for the bucket, so it should start after the bucket exists; and `docker compose up --wait` accepts an exited container only when another service depends on it that way. Without it, `make up` fails with `container wozu-minio-init-1 exited (0)`.

**Read access (proposal to Khalil for BE-08, pending his review of the INF-04 PR).** The bucket is private; the policy grants anonymous `s3:GetObject` on two prefixes only:

| Keys | Anonymous access | How the frontend reads them |
| --- | --- | --- |
| `avatars/*`, `logos/*` | Download only: no listing, no upload | Stable URL `https://<host>/files/avatars/<uid>/<uuid>.jpg` in `avatar_url` / `logo_url` |
| Everything else, e.g. `users/<uid>/intro/<uuid>.mp4` | None | Presigned GET from the API, 5 min |
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
| `make env` | `scripts/init-env.sh`: when `.env` is missing, copies `.env.example` and fills the empty secrets (`JWT_SECRET`, `INTERNAL_API_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`) with `openssl rand -hex 32`; prints their names, never the values; never overwrites an existing `.env` |
| `make up` | `env`, then `infra/proxy/scripts/gen-cert.sh` (the proxy exits without a certificate), then `docker compose up -d --build --wait`, which returns once `db`, `redis` and `api` are healthy and `minio-init` has exited 0 |
| `make down` | stops and removes the containers, keeps volumes |
| `make logs` | last 100 lines of every service, then follows; `make logs s=api` for one service |
| `make test` | starts `db` if needed and creates the test database when it is missing (see below); backend `ruff` + `pytest` in the `api` image (dev tools installed in a throwaway container, code mounted read-only), with `DATABASE_URL` set to `TEST_DATABASE_URL` as in CI; frontend lint, format check, type check and `vitest` in the build stage of its image. Leaves `db` and `redis` running |
| `make https-check` | smoke test of the routes of the one HTTPS origin against the running stack (see One origin over HTTPS) |
| `make files-check` | smoke test of `/files` against the running stack, ends with a Chrome console snippet (see File storage over HTTPS) |
| `make mail-check` | sign-up email end to end through the proxy against the running stack (see Email without a paid service) |
| `make fclean` | removes containers, volumes, the images built here and the certificate; **keeps `.env`**, which holds the hand-added `OPENAI_API_KEY` and the database password that matches the next volume |
| `make re` | `fclean` + `all` |

`down`, `logs` and `fclean` use `--profile '*'`, so they also reach services that are off by default (`worker`).

**Test database.** The backend tests delete what they find, so they run only on `POSTGRES_TEST_DB` (`wozu_test`), never on the app database `POSTGRES_DB`. `infra/db/create-test-db.sh` creates it, owned by `POSTGRES_USER`, with PostGIS (the schema has a `geography` column). It runs in the `db` container from two places: the image runs it once when the `db-data` volume is new (mounted as the single file `/docker-entrypoint-initdb.d/20-create-test-db.sh`, after the image's own `10_postgis.sh`), and `make test` runs it on every call (`docker compose exec`), so a volume created before the script gets the database too. It is idempotent, reads the names from the container environment, connects over the local socket (no password) and refuses a name that equals `POSTGRES_DB` or lacks `test` (the fixtures skip such a database). The tables come from the fixtures, which run `alembic` on `TEST_DATABASE_URL`.

**Test Redis.** `make test` also starts `redis` and passes `TEST_REDIS_URL=redis://redis:6379/1` to pytest only (`-e` in the Makefile), so the 20 WebSocket tests in `tests/test_realtime.py` run, as in CI, instead of being skipped. Database 1 is used only by the tests, which delete only the `ws:` keys they make; the app uses database 0. `TEST_REDIS_URL` is not in the api's runtime environment. The media and picture tests (BE-07, BE-08) still skip in `make test`: they need `TEST_MINIO_*`, which only CI sets.

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
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | `wozu` / generated | minio, minio-init; api and worker as `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` until INF-13 |
| `MINIO_EXTERNAL_ENDPOINT` | `https://localhost` | api, worker: presigned URLs (with the port when `HTTPS_PORT` is not 443) |
| `MINIO_BUCKET` | `files` | api, worker, minio-init; must match the `/files` route |
| `MINIO_REGION` | `us-east-1` | api, worker: signing without a region lookup |
| `SMTP_HOST` / `SMTP_PORT` / `MAIL_FROM` | `mailpit` / `1025` / `no-reply@wozu.local` | api |
| `GRAFANA_ADMIN_PASSWORD` | generated | grafana |
| `OPENAI_API_KEY` | empty, filled by hand | worker |
| `MODERATION_FAIL_OPEN` | `false` on defense day | worker |

Compose passes each service only the variables it needs (`environment:`), not the whole `.env`. Addresses inside the Docker network are written in `docker-compose.yml`, not `.env`: the `db` host in `DATABASE_URL`, `MINIO_ENDPOINT=minio:9000`, and `REDIS_URL=redis://redis:6379/0` for api and worker (`x-backend-env`). The backend's `settings.redis_url` defaults to the same value, but `realtime/connection_manager.py` reads `REDIS_URL` and falls back to `localhost`; inside a container that is the container itself, so without the variable a published event was lost without an error and never reached the other user's `/ws` (found by Khalil in #24).

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

For INF-11, from INF-04: presigned uploads must keep working once `MODSEC_RULE_ENGINE=On`. `PUT` stays in `ALLOWED_METHODS` (CRS rule 911100 scores it otherwise) and the upload content types in `ALLOWED_REQUEST_CONTENT_TYPE` (rule 920420); see "For INF-11" in [infra/proxy/README.md](../../infra/proxy/README.md). `/files` keeps its 60 MB body limit (`client_max_body_size 60m`) and `SecRequestBodyLimitAction ProcessPartial`. `make files-check` and the browser snippet must still pass with blocking on.

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
