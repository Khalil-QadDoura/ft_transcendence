# One command from a fresh clone to a running site: `make`.
# Everything runs in containers; the host needs Docker Engine 25+ (health checks use
# start_interval, which Engine 24 refuses) with compose v2, make, bash and openssl.
# The checks against the running stack (https-check, files-check, mail-check, metrics-check,
# grafana-check) also use curl, and metrics-check and grafana-check python3 3.9+ (macOS
# command line tools; the ubuntu runner).

COMPOSE := docker compose
# Every profile, so down and fclean also reach services with profiles (api-test, redis-test).
COMPOSE_ALL := $(COMPOSE) --profile '*'
# Optional: `make logs s=api` follows one service.
s ?=
# Optional: `make anonymise-deleted days=0` anonymises every deleted account at once.
days ?=

.PHONY: all env certs up down logs logs-reset test https-check images-check secrets-check files-check \
	mail-check metrics-check grafana-check schema-diagram anonymise-deleted alert-demo fclean re

all: env up

# Creates .env with random secrets when it is missing. An existing one keeps every line and
# gets only the keys .env.example has and it lacks (INF-09); the names are printed, not values.
env:
	@./scripts/init-env.sh

# Self-signed certificate for the proxy; keeps an existing pair.
certs:
	@./infra/proxy/scripts/gen-cert.sh

# --wait returns once every service is running (healthy where it has a health check),
# and fails if one of them exits.
up: env certs
	$(COMPOSE) up -d --build --wait --wait-timeout 300
	@port=$$(sed -n 's/^HTTPS_PORT=//p' .env); \
	if [ -z "$$port" ] || [ "$$port" = 443 ]; then url=https://localhost/; else url=https://localhost:$$port/; fi; \
	echo "WOZU Web is up: $$url (mail inbox: $${url}mail/)"

down:
	$(COMPOSE_ALL) down --remove-orphans

# The last 100 lines, then follows; Ctrl-C stops following, the stack keeps running.
logs:
	-$(COMPOSE_ALL) logs -f --tail=100 $(s)

# Empties the logs of the stack (INF-07). Every log of the stack is the json-file log of a
# container (the proxy's access and ModSecurity audit logs included, both on stdout); no log
# is kept in a volume. Docker deletes those files with the container, so this removes the
# stopped containers (e.g. the exited one-shot minio-init) and recreates every running
# service: new containers, empty logs. Named data volumes (database, files, metrics, Grafana)
# are not touched. A dependency that is not running is started, as `make` would (minio-init
# runs again as the api's). Mailpit keeps its inbox inside its container, so the inbox is
# emptied too. Logs are kept at most 30 days (Privacy Policy, PO decision 2026-11-13); the
# operator runs this at least weekly, see "Logs and retention" in docs/infra/infrastructure.md.
logs-reset:
	@running="$$($(COMPOSE_ALL) ps --services --status running | sort | tr '\n' ' ')"; \
	stopped="$$($(COMPOSE_ALL) ps --services --status exited --status created --status dead \
		| sort | tr '\n' ' ')"; \
	if [ -z "$$running$$stopped" ]; then echo "logs-reset: no container, nothing to reset"; exit 0; fi; \
	if [ -n "$$stopped" ]; then $(COMPOSE_ALL) rm --force $$stopped || exit 1; fi; \
	if [ -n "$$running" ]; then \
		$(COMPOSE_ALL) up -d --force-recreate --wait --wait-timeout 300 $$running || exit 1; \
	fi; \
	echo "logs-reset: stopped containers removed: $${stopped:-none}"; \
	echo "logs-reset: recreated with empty logs: $${running:-none}"

# Backend: ruff + pytest in a throwaway api-test container (profile test): the test stage of
# backend/Dockerfile, which is the api runtime image plus requirements-dev.txt, run as the same
# non-root user, with the code mounted read-only. The tests get only the test database: db starts
# first (also from a stopped stack), the script that runs on a new volume creates the test
# database when it is missing, and pytest sees DATABASE_URL = TEST_DATABASE_URL, as in CI.
# Redis: the tests get their own server, redis-test (profile test), as CI gets a Redis service
# container. Pub/sub and CLIENT KILL ignore database numbers, so database 1 of the site's redis
# would send test events to open /ws sockets and cut them off. TEST_REDIS_URL (the tests' own
# clients, and build_app's redis_url) and REDIS_URL (the app's settings.redis_url, read by
# every Settings a test builds without that override) both point at it, set only here, as the
# CI backend job points both at its Redis service; --no-deps keeps `run` from starting the
# api's own dependencies (redis, minio-init), which the tests do not use.
# Frontend: the checks of its CI job, in the build stage of its image.
# The MinIO tests use their own buckets (media-test, pictures-test) on the dev MinIO, with
# the api container's own keys: they never appear on a command line or in this output.
# As in CI, a skipped backend test fails make test (-rs prints why it was skipped), and a test
# that runs longer than 300 s prints the stack of every thread (faulthandler_timeout) instead
# of hanging silently; the test keeps running.
test: env
	$(COMPOSE) --profile test up -d --wait db redis-test minio
	$(COMPOSE) exec -T db /docker-entrypoint-initdb.d/20-create-test-db.sh
	$(COMPOSE) --profile test run --rm --no-deps --build -v $(CURDIR)/backend:/src:ro -w /src \
		-e TEST_REDIS_URL=redis://redis-test:6379/0 -e REDIS_URL=redis://redis-test:6379/0 \
		-e TEST_MINIO_ENDPOINT=minio:9000 api-test \
		sh -c 'ruff check --no-cache . \
		&& ruff format --check --no-cache . \
		&& DATABASE_URL="$$TEST_DATABASE_URL" TEST_MINIO_ACCESS_KEY="$$MINIO_ACCESS_KEY" \
		TEST_MINIO_SECRET_KEY="$$MINIO_SECRET_KEY" pytest -q -rs -p no:cacheprovider \
		-o faulthandler_timeout=300 --junitxml=/tmp/pytest-results.xml \
		&& python -c "import sys, xml.etree.ElementTree as ET; \
		suites = ET.parse(\"/tmp/pytest-results.xml\").getroot().iter(\"testsuite\"); \
		skipped = sum(int(suite.get(\"skipped\", \"0\")) for suite in suites); \
		sys.exit(f\"{skipped} tests skipped; make test must run every backend test, as CI\" \
		if skipped else 0)"'
	docker build -q --target build -t wozu-frontend-test ./frontend
	docker run --rm wozu-frontend-test \
		sh -c 'npm run lint && npm run format:check && npm run typecheck && npm test'

# Routes of the one HTTPS origin against the running stack: frontend with SPA fallback,
# /api, the /ws handshake, redirects, internal routes blocked (INF-03).
https-check:
	@./infra/proxy/smoke-test.sh

# Fails when a compose image, a Dockerfile FROM or an image a GitHub Actions workflow pulls
# (service containers, container:, docker:// steps; INF-06) is not pinned as
# name:tag@sha256:... or uses latest; prints each offender (INF-07). Needs no running stack
# and no .env.
images-check:
	@./scripts/images-check.sh

# Secrets (keys, passwords, tokens) in any commit of any branch, with gitleaks (pinned) on a
# fresh mirror clone: never reads .env or another ignored file; prints REDACTED instead of
# a value. Findings checked by hand and known not to be secrets: .gitleaksignore. Needs only
# Docker and git (BE-13).
secrets-check:
	@./scripts/secrets-check.sh

# Draws docs/db/schema.svg, the database picture in the README, from a throwaway PostgreSQL +
# PostGIS built by `alembic upgrade head` (eralchemy and Graphviz, pinned versions); removes
# what it started. Run it after a migration changes the schema and commit the picture. Needs
# only Docker: no .env, no port published, the running stack is left alone (BE-14).
schema-diagram:
	@./scripts/gen-schema-diagram.sh

# Presigned upload and download through https://<host>/files and the bucket policy, against
# the running stack; ends with a snippet for the Chrome console (INF-04).
files-check:
	@./infra/minio/smoke-test.sh

# Sign-up email end to end through the proxy: register, the message in Mailpit at /mail,
# its link to the frontend, verify, login; deletes the message afterwards (INF-05).
mail-check:
	@./infra/mailpit/smoke-test.sh

# Monitoring against the running stack: every Prometheus target up (prometheus, api,
# postgres, redis, cadvisor), one real series per source (pg_up, redis_up, the api
# container's CPU and memory, the API's request counter) and the retention decided for
# metrics (30d, 1GB) (INF-08); the alert rules: promtool check rules and promtool test rules
# (infra/prometheus/alerts.yml, alerts.test.yml), and the five rules loaded, healthy,
# evaluated every 15 s (INF-10). Queries Prometheus inside its container, which has no host
# port; retries for up to 60 s.
metrics-check:
	@./infra/prometheus/smoke-test.sh

# Dashboards against the running stack, over HTTPS through the proxy: /grafana/ redirects to
# the login on the public origin, health 200, no anonymous access or sign-up, the security
# settings as decided (public dashboards and snapshots off among them), the
# Prometheus datasource healthy, both dashboards in the folder WOZU with every panel query
# returning data (dashboard variables at their saved value), the Firing alerts panel with
# one series and the five Prometheus alert rules listed by Grafana (INF-10), deletion
# refused, Grafana Live (WebSocket) 101 and a
# wrong password 401 (for the non-existent user grafana-check-nobody, so admin is never
# locked, however often it runs). Logs in as admin with the password from the grafana
# container, never printed; retries for up to 60 s (INF-09).
grafana-check:
	@./infra/grafana/smoke-test.sh

# The second stage of account deletion now, instead of at the worker's nightly run (BE-34), on
# the running stack: anonymises the deleted accounts that are due and deletes their files.
# By default those deleted more than 30 days ago, as the nightly run; `days=0` takes every
# deleted account at once (the demo). Accounts on retention hold are always skipped.
anonymise-deleted:
	$(COMPOSE) exec -T worker python -m app.worker.tasks.anonymise $(if $(days),--older-than-days $(days))

# Live alert demo, manual only (not in CI): stops Redis, waits until the RedisDown alert
# fires (prints the seconds; fails after 120 s), keeps Redis down 25 s more so the Firing
# alerts panel shows it (`ALERT_HOLD_SEC=0 make alert-demo` skips that), starts Redis again
# and waits until the alert is resolved (fails after 120 s). Redis is started again however
# it ends (INF-10).
alert-demo:
	@./infra/prometheus/alert-demo.sh

# Removes containers, volumes (database, files), images built here and the certificate.
# Keeps .env: it holds the hand-added OPENAI_API_KEY and matches the next database volume.
fclean:
	$(COMPOSE_ALL) down -v --rmi local --remove-orphans
	@docker image rm wozu-frontend-test >/dev/null 2>&1 || true
	rm -rf infra/proxy/certs

re: fclean
	@$(MAKE) --no-print-directory all
