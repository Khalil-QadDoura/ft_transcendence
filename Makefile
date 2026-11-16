# One command from a fresh clone to a running site: `make`.
# Everything runs in containers; the host needs Docker Engine 25+ (health checks use
# start_interval, which Engine 24 refuses) with compose v2, make, bash and openssl.
# The checks against the running stack (https-check, files-check, mail-check, metrics-check)
# also use curl, and metrics-check python3 (macOS command line tools; the ubuntu runner).

COMPOSE := docker compose
# Every profile, so down and fclean also reach services that are off by default (worker).
COMPOSE_ALL := $(COMPOSE) --profile '*'
# Optional: `make logs s=api` follows one service.
s ?=

.PHONY: all env certs up down logs test https-check images-check files-check mail-check metrics-check \
	fclean re

all: env up

# Creates .env with random secrets when it is missing; keeps an existing one.
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

# Backend: ruff + pytest in a throwaway api-test container (profile test): the test stage of
# backend/Dockerfile, which is the api runtime image plus requirements-dev.txt, run as the same
# non-root user, with the code mounted read-only. The tests get only the test database: db starts
# first (also from a stopped stack), the script that runs on a new volume creates the test
# database when it is missing, and pytest sees DATABASE_URL = TEST_DATABASE_URL, as in CI.
# Redis: the tests get their own server, redis-test (profile test), as CI gets a Redis service
# container. Pub/sub and CLIENT KILL ignore database numbers, so database 1 of the site's redis
# would send test events to open /ws sockets and cut them off. TEST_REDIS_URL (the WebSocket and
# media tests) and REDIS_URL (the app's connection_manager, used by the conversation tests)
# both point at it, set only here; --no-deps keeps `run` from starting the api's own
# dependencies (redis, minio-init), which the tests do not use.
# Frontend: the checks of its CI job, in the build stage of its image.
# The MinIO tests use their own buckets (media-test, pictures-test) on the dev MinIO, with
# the api container's own keys: they never appear on a command line or in this output.
# As in CI, a skipped backend test fails make test (-rs prints why it was skipped).
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
		--junitxml=/tmp/pytest-results.xml && python -c "import sys, xml.etree.ElementTree as ET; \
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

# Fails when a compose image or a Dockerfile FROM is not pinned as name:tag@sha256:... or
# uses latest; prints each offender (INF-07). Needs no running stack and no .env.
images-check:
	@./scripts/images-check.sh

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
# metrics (30d, 1GB). Queries Prometheus inside its container, which has no host port;
# retries for up to 60 s (INF-08).
metrics-check:
	@./infra/prometheus/smoke-test.sh

# Removes containers, volumes (database, files), images built here and the certificate.
# Keeps .env: it holds the hand-added OPENAI_API_KEY and matches the next database volume.
fclean:
	$(COMPOSE_ALL) down -v --rmi local --remove-orphans
	@docker image rm wozu-frontend-test >/dev/null 2>&1 || true
	rm -rf infra/proxy/certs

re: fclean
	@$(MAKE) --no-print-directory all
