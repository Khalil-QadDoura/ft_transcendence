#!/usr/bin/env bash
# Check of the backups (INF-14), against the running stack:
# - the backup service runs, is healthy (its heartbeat), and keeps BACKUP_KEEP = 7 copies;
# - `make backup` writes a copy; result=ok in its status;
# - the newest dump reads to the end (pg_restore) and lists every app table of the database;
# - the newest files copy has as many files as the bucket has objects, and one object (the
#   first by name) has the same sha256 in the copy and in the bucket;
# - retention on a test directory inside the container: 7 + 2 older fake copies of each
#   kind, a .partial of two days ago and a fresh one -> exactly the 7 newest of each remain,
#   the old .partial is gone, the fresh one stays (a run may be writing it); the result is
#   compared with the decided 7, not with the service's own BACKUP_KEEP;
# - the backups volume: no host port on the backup container, no other container mounts it,
#   and the proxy does not serve its files.
# When the bucket is empty (CI), one probe object is uploaded first, so the copy and the
# checksum have something to compare, and removed at the end. The real backups stay.
# Needs the stack up (`make`). Run it with `make backup-check`. Exits 1 when a check fails.
# Works with bash 3.2 (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
CA="$ROOT/infra/proxy/certs/server.crt"
# The retention decided by the PO (one week of daily copies; Privacy Policy section 6).
DECIDED_KEEP=7

for service in proxy db minio backup; do
    if [ -z "$(docker compose ps -q --status running "$service")" ]; then
        echo "backup-check: $service is not running; start the stack with make" >&2
        exit 1
    fi
done
cid="$(docker compose ps -q backup)"
in_backup() { docker compose exec -T backup "$@"; }

https_port="$(docker compose port proxy 8443)"
https_port="${https_port##*:}"
if [ "$https_port" = 443 ]; then base=https://localhost; else base="https://localhost:$https_port"; fi

failed=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failed=1; }

bucket="$(in_backup printenv MINIO_BUCKET)"
probe=""
work="$(mktemp -d)"
cleanup() {
    if [ -n "$probe" ]; then
        in_backup backup.sh mc rm --quiet "store/$bucket/$probe" >/dev/null 2>&1 || true
    fi
    in_backup rm -rf /tmp/retention-check >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

echo "backup-check: service backup, bucket $bucket"

echo "Service:"
health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
if [ "$health" = healthy ]; then
    pass "backup container healthy (heartbeat younger than 3 minutes)"
else
    fail "backup container health: $health, expected healthy (make logs s=backup)"
fi
keep="$(in_backup printenv BACKUP_KEEP || true)"
if [ "$keep" = "$DECIDED_KEEP" ]; then
    pass "BACKUP_KEEP = $keep (decided: $DECIDED_KEEP)"
else
    fail "BACKUP_KEEP = ${keep:-unset}, decided: $DECIDED_KEEP"
fi
pass "BACKUP_TIME = $(in_backup printenv BACKUP_TIME || true) in TZ $(in_backup printenv TZ || true)"
user="$(docker inspect -f '{{.Config.User}}' "$cid")"
if [ -n "$user" ] && [ "${user%%:*}" != 0 ] && [ "${user%%:*}" != root ]; then
    pass "runs as user $user, not root"
else
    fail "runs as user '${user:-root}', expected a non-root user"
fi

objects="$(in_backup backup.sh mc ls --recursive "store/$bucket" | wc -l | tr -d ' ')"
if [ "$objects" = 0 ]; then
    probe="backup-check/probe-$(date -u +%Y%m%dT%H%M%SZ).txt"
    echo "backup-check probe $(date -u)" | in_backup backup.sh mc pipe --quiet "store/$bucket/$probe" >/dev/null
    echo "  (bucket empty: probe object $probe uploaded for this check)"
fi

echo "make backup:"
if make --no-print-directory backup > "$work/run.txt" 2>&1; then
    pass "make backup: exit 0"
else
    fail "make backup: exit $?"
fi
sed 's/^/        /' "$work/run.txt"
if grep -qx 'result=ok' "$work/run.txt"; then
    pass "status: result=ok"
else
    fail "status: $(grep '^result=' "$work/run.txt" || echo 'no result line'), expected result=ok"
fi
ts="$(sed -n 's/^copy=//p' "$work/run.txt")"
latest="$(in_backup backup.sh resolve latest 2>/dev/null || true)"
if [ -n "$ts" ] && [ "$ts" = "$latest" ]; then
    pass "copy $ts is the newest complete copy"
else
    fail "copy of this run: ${ts:-none}, newest complete copy: ${latest:-none}"
fi

if [ -n "$latest" ]; then
    echo "Newest dump (db/db-$latest.dump):"
    if out="$(in_backup backup.sh verify-db "/backups/db/db-$latest.dump" 2>&1)"; then
        pass "valid: $out"
    else
        fail "not valid: $out"
    fi

    echo "Newest files copy (files/files-$latest/):"
    want="$(in_backup backup.sh mc ls --recursive "store/$bucket" | wc -l | tr -d ' ')"
    got="$(in_backup find "/backups/files/files-$latest" -type f | wc -l | tr -d ' ')"
    if [ "$got" = "$want" ] && [ "$got" -gt 0 ]; then
        pass "$got files, the bucket has $want objects"
    else
        fail "$got files, the bucket has $want objects"
    fi
    sample="$(in_backup sh -c "cd /backups/files/files-$latest && find . -type f | sort | sed -n 1p")"
    sample="${sample#./}"
    if [ -n "$sample" ]; then
        copy_sum="$(in_backup sha256sum "/backups/files/files-$latest/$sample" | cut -d' ' -f1)"
        bucket_sum="$(in_backup sh -c 'backup.sh mc cat "$1" | sha256sum' sh "store/$bucket/$sample" | cut -d' ' -f1)"
        if [ -n "$copy_sum" ] && [ "$copy_sum" = "$bucket_sum" ]; then
            pass "sha256 of $sample: the same in the copy and in the bucket (${copy_sum:0:16}…)"
        else
            fail "sha256 of $sample: copy ${copy_sum:-none}, bucket ${bucket_sum:-none}"
        fi
    else
        fail "no file in files/files-$latest/ to compare"
    fi
fi

echo "Retention (test directory /tmp/retention-check in the container):"
fakes=$((DECIDED_KEEP + 2))
# Fake copies dated 2000-01-01 .. 2000-01-09, an old and a fresh .partial of each kind.
in_backup bash -c '
    set -e
    root=/tmp/retention-check
    rm -rf "$root"
    mkdir -p "$root/db" "$root/files"
    for i in $(seq 1 '"$fakes"'); do
        ts="200001$(printf %02d "$i")T000000Z"
        echo fake > "$root/db/db-$ts.dump"
        mkdir "$root/files/files-$ts"
        echo fake > "$root/files/files-$ts/object.txt"
    done
    echo fake > "$root/db/db-19990101T000000Z.dump.partial"
    mkdir "$root/files/files-19990101T000000Z.partial"
    touch -d "2 days ago" "$root/db/db-19990101T000000Z.dump.partial" "$root/files/files-19990101T000000Z.partial"
    echo fake > "$root/db/db-20991231T000000Z.dump.partial"
    mkdir "$root/files/files-20991231T000000Z.partial"
'
in_backup backup.sh retention /tmp/retention-check | sed 's/^/        /'
listing="$(in_backup sh -c 'cd /tmp/retention-check && ls -1 db files')"
db_left="$(printf '%s\n' "$listing" | grep -Ec '^db-[0-9]{8}T[0-9]{6}Z\.dump$' || true)"
files_left="$(printf '%s\n' "$listing" | grep -Ec '^files-[0-9]{8}T[0-9]{6}Z$' || true)"
oldest_kept="$(printf '%s\n' "$listing" | grep -E '^db-[0-9]{8}T[0-9]{6}Z\.dump$' | sort | sed -n 1p)"
expected_oldest="db-200001$(printf %02d $((fakes - DECIDED_KEEP + 1)))T000000Z.dump"
if [ "$db_left" = "$DECIDED_KEEP" ] && [ "$oldest_kept" = "$expected_oldest" ]; then
    pass "database copies: $fakes -> $db_left, the newest kept (oldest left $oldest_kept)"
else
    fail "database copies: $fakes -> $db_left (oldest left ${oldest_kept:-none}), expected the newest $DECIDED_KEEP"
fi
if [ "$files_left" = "$DECIDED_KEEP" ]; then
    pass "files copies: $fakes -> $files_left"
else
    fail "files copies: $fakes -> $files_left, expected $DECIDED_KEEP"
fi
if ! printf '%s\n' "$listing" | grep -q '^db-19990101T000000Z\.dump\.partial$' \
    && ! printf '%s\n' "$listing" | grep -q '^files-19990101T000000Z\.partial$'; then
    pass ".partial leftovers older than a day removed"
else
    fail ".partial leftovers of two days ago still there"
fi
if printf '%s\n' "$listing" | grep -q '^db-20991231T000000Z\.dump\.partial$' \
    && printf '%s\n' "$listing" | grep -q '^files-20991231T000000Z\.partial$'; then
    pass "fresh .partial kept (a run may be writing it)"
else
    fail "fresh .partial removed"
fi

echo "Backups volume:"
bindings="$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$cid")"
case "$bindings" in
    '{}' | null) pass "backup container publishes no host port" ;;
    *) fail "backup container publishes $bindings" ;;
esac
volume="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/backups"}}{{.Name}}{{end}}{{end}}' "$cid")"
if [ -n "$volume" ]; then
    users="$(docker ps -a --filter "volume=$volume" --format '{{.ID}}' | sort -u)"
    if [ "$users" = "$(docker inspect -f '{{.Id}}' "$cid" | cut -c1-12)" ]; then
        pass "only the backup container mounts the backups volume"
    else
        fail "other containers mount the backups volume: $(docker ps -a --filter "volume=$volume" --format '{{.Names}}' | tr '\n' ' ')"
    fi
else
    fail "no named volume mounted at /backups in the backup container"
fi
for path in "backups/status" "backups/db/db-$latest.dump" "db/db-$latest.dump" "files/../backups/status"; do
    code="$(curl -sS --cacert "$CA" -o "$work/body" -w '%{http_code}' "$base/$path" 2>/dev/null || echo 000)"
    if head -c 5 "$work/body" | grep -q PGDMP || grep -q '^last_run=' "$work/body"; then
        fail "GET /$path: $code with backup content"
    else
        pass "GET /$path: $code, no backup content"
    fi
done

if [ "$failed" -ne 0 ]; then
    echo "backup-check: FAILED"
    exit 1
fi
echo "backup-check: all checks passed"
