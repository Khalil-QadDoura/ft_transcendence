#!/bin/sh
# with-secrets (INF-13): the entrypoint wrapper of every service that gets its secrets
# from a Vault Agent sidecar. Compose mounts it read-only at /usr/local/bin/with-secrets and
# puts it in front of the image's own entrypoint or command:
#   with-secrets COMMAND [ARG...]
# 1. waits until every file in VAULT_SECRET_FILES (space-separated) and VAULT_ENV_FILE exists
#    and is not empty: the service's Vault Agent renders them into a tmpfs volume once Vault
#    is unsealed; after a Docker or host restart Vault is sealed until `make` unseals it.
#    Without this wait a service could start without its secrets (MinIO, for one, then
#    starts with its default credentials minioadmin:minioadmin);
# 2. exports every NAME='value' line of VAULT_ENV_FILE (api, worker, api-test, minio-init);
# 3. runs COMMAND in its place (exec), so it keeps PID 1 and gets the signals.
# Gives up after VAULT_WAIT_SEC seconds (default 300) with exit 1; `restart: unless-stopped`
# then starts the container again. Never prints a value.
# For a command in a running container, which `docker compose exec` starts without the
# entrypoint: `docker compose exec worker with-secrets python -m ...`.
set -eu

wait_max="${VAULT_WAIT_SEC:-300}"
waited=0
for f in ${VAULT_SECRET_FILES:-} ${VAULT_ENV_FILE:-}; do
    while [ ! -s "$f" ]; do
        if [ "$waited" -eq 0 ]; then
            echo "with-secrets: waiting for $f from this service's Vault Agent (sealed Vault? run make)" >&2
        fi
        if [ "$waited" -ge "$wait_max" ]; then
            echo "with-secrets: $f still missing after ${wait_max}s; is Vault unsealed? Run make" >&2
            exit 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
done
if [ -n "${VAULT_ENV_FILE:-}" ]; then
    set -a
    # shellcheck disable=SC1090 # rendered at run time by the Vault Agent
    . "$VAULT_ENV_FILE"
    set +a
fi
exec "$@"
