# Front proxy

nginx + ModSecurity v3 + OWASP Core Rule Set: the only door from the browser to the stack, on one HTTPS origin. The decision and its reasons are in the decisions log of [overview.md](../../docs/plan/overview.md); the routing rationale is in [infrastructure.md](../../docs/infra/infrastructure.md).

INF-01 delivers this configuration only. INF-02 adds the service to `docker-compose.yml`; INF-11 turns on blocking and tunes the rules.

## Image

`owasp/modsecurity-crs:4.30.0-nginx-alpine-202610180210`

Digest `sha256:873ce68a658d2e3b61484a8a24d215f7d15456e7ce5aec5e7114bf000d743365` (multi-arch: amd64, arm64). CRS 4.30.0, nginx 1.30.6, libmodsecurity 3.0.17. The tag names one dated build; `nginx-alpine` floats to the newest one. To bump it, change the tag here, in infrastructure.md and in compose, then rerun the checks below.

## Which files are ours

The image renders every `/etc/nginx/templates/**/*.template` with envsubst into `/etc/nginx/` at start. A file mounted at the same path replaces the image's version; everything else stays the image's.

| File in the container | Owner | What it does |
| --- | --- | --- |
| `templates/conf.d/default.conf.template` | **Ours**, mounted from this folder | Listeners, TLS, routing table |
| `templates/conf.d/logging.conf.template` | **Ours**, mounted over the image's | Access log without the query string on token routes (QA-01, see Access log) |
| `/etc/nginx/conf/server.{crt,key}` | **Ours**, generated into `certs/`, image default path | Certificate and key |
| Environment | **Ours**, `proxy.env` | Rule engine mode, OCSP stapling off, default HTTPS port for the redirect |
| `templates/nginx.conf.template` | Image | Loads the ModSecurity module, sets `resolver` from `/etc/resolv.conf` (`127.0.0.11` in Docker) |
| `templates/conf.d/modsecurity.conf.template` | Image | `modsecurity on` + `modsecurity_rules_file`, at `http` level, so it covers every location |
| `templates/modsecurity.d/*`, `/opt/owasp-crs` | Image | ModSecurity settings and the CRS rules |
| `templates/includes/location_common.conf.template` | Image, included by our template | `/healthz` (used by the proxy health check in compose, INF-07), `/50x.html` |

## Routes

| Path | Upstream | Notes |
| --- | --- | --- |
| `http://` any | none | 301 to `https://`, path, query and the HTTPS host port kept |
| `/` | `frontend:80` | The frontend container does the SPA fallback; a missing `/assets/*` file is a 404 |
| `/api/*` | `api:8000` | Full path kept; `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`; 1 MB body limit |
| `/ws*` | `api:8000` | Upgrade headers, one-hour timeouts, no buffering |
| `/files/*` | `minio:9000` | Host and URI unchanged for presigned signatures; 60 MB body limit, no buffering; `Content-Security-Policy: sandbox` and `X-Content-Type-Options: nosniff` on every answer (MinIO's own `nosniff` hidden), so an uploaded HTML file cannot run as our origin |
| `/grafana/*` | `grafana:3000` | Full path kept (`serve_from_sub_path`), upgrade headers |
| `/mail/*` | `mailpit:8025` | Full path kept (`MP_WEBROOT=/mail/`), upgrade headers |
| `/_internal*`, `/metrics*`, `/api/_internal*`, `/api/metrics*` | none | 404, including the image's `/metrics/nginx`; matched on the decoded, normalized path |
| `/healthz` | none | 200 `OK` from the image's include |

Upstream names resolve per request, so the proxy starts with any upstream missing and answers 502 on that route only; the route comes back with no proxy restart once the service is up (`resolver` caches names for 5 seconds).

The API mounts its internal routes at `/_internal` and BE-30 plans `/metrics` at the root; both stay reachable inside the Docker network (`http://api:8000/...`). The `/api/` variants are closed too, so a router mounted under `/api` by mistake does not become public. Internal routes belong under `/_internal`, never in the `/api` router.

nginx's own trailing-slash redirects (`/mail` → `/mail/`) send a relative `Location` (`absolute_redirect off`): an absolute one drops a non-default host port, because the image sets `port_in_redirect off` and nginx only knows its listen port 8443 anyway. `infra/frontend/default.conf` does the same for the frontend container's `/assets` → `/assets/`.

`make https-check` (`smoke-test.sh` in this folder) checks every route above against the running stack; `/ws` passes only with `101 Switching Protocols` to a ticketless handshake. See "One origin over HTTPS" in infrastructure.md.

## Ports

The image runs as the unprivileged `nginx` user (uid 101) and cannot bind below 1024, so it listens on 8080 and 8443 inside the container. The host publishes the ports from infrastructure.md: `80:8080`, `443:8443` by default, or `HTTP_PORT` / `HTTPS_PORT` from `.env`. Compose passes the HTTPS host port to the template as `PUBLIC_HTTPS_PORT`; the redirect adds it to the URL when it is not 443 (`http://localhost:8080/` → `https://localhost:8443/`).

## Certificate

```
infra/proxy/scripts/gen-cert.sh           # keeps an existing pair
infra/proxy/scripts/gen-cert.sh --force   # replaces it
```

Writes `certs/server.crt` and `certs/server.key` (git-ignored): CN `localhost`, SAN `DNS:localhost`, `IP:127.0.0.1`, 825 days. Browsers warn because nothing they trust signed it; the warning is accepted once per browser profile. The key is mode 0644 on purpose: the container reads the bind mount as uid 101, and on Linux a 0600 key owned by the host user fails with "Permission denied".

## In compose

The `proxy` service in the root `docker-compose.yml` (INF-02) mounts the template and `certs/`, reads `proxy.env`, and sets `SERVER_NAME` (from `DOMAIN`) and `PUBLIC_HTTPS_PORT`.

`gen-cert.sh` must run before `docker compose up`; `make up` runs it first. Without `certs/server.key` the image tries to generate its own certificate inside the read-only mount, fails with "Read-only file system", and the container exits with code 1.

## Trying it without the stack

```
infra/proxy/scripts/gen-cert.sh
docker network create inf01-test
docker run -d --name inf01-proxy --network inf01-test -p 80:8080 -p 443:8443 \
  --env-file infra/proxy/proxy.env \
  -v "$PWD/infra/proxy/templates/conf.d/default.conf.template:/etc/nginx/templates/conf.d/default.conf.template:ro" \
  -v "$PWD/infra/proxy/certs:/etc/nginx/conf:ro" \
  owasp/modsecurity-crs:4.30.0-nginx-alpine-202610180210
docker exec inf01-proxy nginx -t
curl -sI http://localhost/                 # 301 to https://localhost/
curl -sk https://localhost/healthz         # OK
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/metrics   # 404
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost/api/x     # 502 until an api service exists
docker rm -f inf01-proxy && docker network rm inf01-test
```

Two traps when testing with stubs:

- WebSocket checks need `curl --http1.1`. Over HTTP/2 curl drops the `Connection` and `Upgrade` headers, and browsers open WebSockets over HTTP/1.1 anyway.
- `traefik/whoami` stalls on uploads through this proxy: a PUT of 1 MB or 50 MB stops at about 500 KB of response until a timeout, while the same PUT straight to whoami takes about a second, and real MinIO takes 50 MB through the proxy in under a second. whoami echoes the request body back; the cause is not pinned down. Upload tests need real MinIO.

## Access log

One line per request on the container's stdout, the image's format `main` with one field changed (QA-01, PO decision, byul-byul, 2026-11-25): for `/verify-email`, `/reset-password`, `/api/auth/`, `/files/` and `/ws` (path prefixes) the request line is method, path and protocol, without the query string, which carries the email link tokens, the 42 callback's `code` and `state`, presigned URL signatures and the WebSocket ticket. Every other request is logged with its request line as sent, query included (a jobs search stays visible). The `map` in `templates/conf.d/logging.conf.template` matches `$request_uri`, the URI as the client sent it, not `$uri`: when an upstream fails, `error_page` sends the request to `/50x.html`, `$uri` changes with it, and a map on `$uri` would log the token of exactly that request.

```
curl -sk -o /dev/null 'https://localhost/verify-email?token=PROBE'
docker compose logs --no-log-prefix proxy 2>&1 | grep 'verify-email'   # GET /verify-email HTTP/2.0, no token
```

## WAF logs

Each match goes to the container's stdout as one JSON audit line: `transaction.messages[].details.ruleId`. In DetectionOnly the request still goes through. A SQL injection probe logs rule 942100 and the anomaly total 949110.

```
docker compose logs --no-log-prefix proxy 2>&1 | grep '"transaction"'
```

The audit line has parts `AHZ` only (`MODSEC_AUDIT_LOG_PARTS` in `proxy.env`, PO decision, byul-byul, 2026-11-17): A is the client IP and port, the time, the unique ID and the request line (method, host, URI with query string); H is the matched rules with their scores and the response status; Z ends the entry. It holds no request or response header and no body. `Authorization` and `Cookie` carry passwords, Bearer tokens and session cookies, and the image default `ABIJDEFHZ` wrote them into the log for every audited request. INF-11 may add parts for tuning, never `B` (request headers), `I` or `J` (request bodies) or `E` (response body).

## For INF-11

Setting `MODSEC_RULE_ENGINE=On` in `proxy.env` makes SQLi and XSS probes return 403, but as it stands it also blocks normal traffic. Both of these were seen with the engine on:

- `PATCH`, `DELETE` and `PUT` score on rule 911100, and video uploads also on 920420. These two settings cleared them in a test; the exact lists need tuning against the real app:

  ```
  ALLOWED_METHODS=GET HEAD POST OPTIONS PUT PATCH DELETE
  ALLOWED_REQUEST_CONTENT_TYPE=|application/x-www-form-urlencoded| |multipart/form-data| |text/xml| |application/xml| |application/json| |video/mp4| |video/webm| |image/jpeg| |image/png|
  ```

- M13 asks for paranoia level 2 (`BLOCKING_PARANOIA=2`); the image default is 1. Expect more false positives once that changes.

`/files` uses `SecRequestBodyLimitAction ProcessPartial` so a video over the 13 MB `SecRequestBodyLimit` is not rejected. Do not replace it with `SecRequestBodyAccess Off`: that also stops the phase 2 rules on the route, which include SQLi rule 942100.
