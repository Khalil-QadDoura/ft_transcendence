# One command from a fresh clone to a running site: `make`.
# Everything runs in containers; the host needs Docker (with compose v2), make, bash and openssl.

COMPOSE := docker compose
# Every profile, so down and fclean also reach services that are off by default (worker).
COMPOSE_ALL := $(COMPOSE) --profile '*'
# Optional: `make logs s=api` follows one service.
s ?=

.PHONY: all env certs up down logs test fclean re

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

# Backend: ruff + pytest in the api image, with the dev tools installed into a throwaway
# container and the code mounted read-only. Frontend: the checks of its CI job, in the
# build stage of its image.
test: env
	$(COMPOSE) run --rm --build --user root -v $(CURDIR)/backend:/src:ro -w /src \
		-e PIP_ROOT_USER_ACTION=ignore -e PIP_DISABLE_PIP_VERSION_CHECK=1 api \
		sh -c 'pip install -q -r requirements-dev.txt && ruff check --no-cache . \
		&& ruff format --check --no-cache . && pytest -q -p no:cacheprovider'
	docker build -q --target build -t wozu-frontend-test ./frontend
	docker run --rm wozu-frontend-test \
		sh -c 'npm run lint && npm run format:check && npm run typecheck && npm test'

# Removes containers, volumes (database, files), images built here and the certificate.
# Keeps .env: it holds the hand-added OPENAI_API_KEY and matches the next database volume.
fclean:
	$(COMPOSE_ALL) down -v --rmi local --remove-orphans
	@docker image rm wozu-frontend-test >/dev/null 2>&1 || true
	rm -rf infra/proxy/certs

re: fclean
	@$(MAKE) --no-print-directory all
