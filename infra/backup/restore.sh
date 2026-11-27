#!/usr/bin/env bash
# make restore BACKUP=<timestamp|latest> (INF-15): puts one backup run back, the database
# and the bucket of the same moment. Run from the host; the restore itself runs in one-off
# containers of the backup service (`compose run --no-deps`), the only service that mounts
# the backups volume. Order:
#   1. db and minio (with minio-init, which creates the bucket on a new volume) are started;
#      the api is not, so its migrations never create empty tables first. The backup
#      service is stopped: it waits for a healthy api to start, and its loop must take no
#      catch-up or scheduled copy of the state being replaced;
#   2. the copy is chosen and shown; the question is asked unless RESTORE_YES=1;
#   3. api and worker (the writers) are stopped;
#   4. pg_restore --clean --if-exists --no-owner into POSTGRES_DB, in one transaction;
#   5. mc mirror --overwrite --remove of the files copy into the bucket.
# The Makefile then runs `make` (the api starts on the restored database; its migrations
# find alembic_version and add only newer ones) and `restore.sh --next-checks`.
# When a step fails, the script stops there and the api stays stopped: fix, run it again.
# Works with bash 3.2 (macOS). See docs/disaster-recovery.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = --next-checks ]; then
    cat <<'EOF'
restore: the stack is up again. Next checks:
  - log in at the site's /login with an account that existed at the backup time, open its
    profile: the avatar shows and the intro video plays (My Videos);
  - make https-check files-check mail-check   (routes, /files, sign-up email)
  - make backup-check                          (a new backup of the restored state)
  - make logs s=api                            (migrations: no error after the restore)
Everything is as it was at the backup time: what was created since is gone, and what was
deleted since is back (an account or video deleted since must be deleted again; see
"After a restore" in docs/disaster-recovery.md).
EOF
    exit 0
fi

if [ -z "${BACKUP:-}" ]; then
    echo "restore: usage: make restore BACKUP=<timestamp|latest> [RESTORE_YES=1]; make backup-list shows the timestamps" >&2
    exit 1
fi

start=$(date +%s)
echo "restore: starting db and minio (not the api); stopping the backup loop"
docker compose up -d --wait --wait-timeout 300 db minio
# A one-shot: `up --wait` fails on a listed service that exits, even with 0.
docker compose run --rm --no-deps minio-init
docker compose stop backup
docker compose build backup
# backup.sh is the image's entrypoint; --no-deps keeps the api down.
in_backup() { docker compose run --rm --no-deps -T backup "$@"; }

ts="$(in_backup resolve "$BACKUP")"
echo "restore: chosen copy $ts (UTC):"
in_backup list | grep "^$ts " || true

project="${COMPOSE_PROJECT_NAME:-the compose project of docker-compose.yml}"
cat <<EOF
restore: this replaces, in $project,
  - the app database with db/db-$ts.dump,
  - every object of the bucket with files/files-$ts/ (objects not in the copy are deleted).
Everything written after $ts is lost. api and worker are stopped meanwhile.
EOF
if [ "${RESTORE_YES:-}" != 1 ]; then
    if [ ! -t 0 ]; then
        echo "restore: no terminal to ask; run it with RESTORE_YES=1 to confirm" >&2
        exit 1
    fi
    printf 'restore: type yes to continue: '
    read -r answer
    if [ "$answer" != yes ]; then
        echo "restore: cancelled, the database and the bucket are unchanged" >&2
        exit 1
    fi
fi

echo "restore: stopping the writers (api, worker)"
docker compose --profile '*' stop api worker

t=$(date +%s)
in_backup restore-db "$ts"
echo "restore: database in $(($(date +%s) - t))s"
t=$(date +%s)
in_backup restore-files "$ts"
echo "restore: bucket in $(($(date +%s) - t))s"
echo "restore: copy $ts restored in $(($(date +%s) - start))s; starting the stack with make"
