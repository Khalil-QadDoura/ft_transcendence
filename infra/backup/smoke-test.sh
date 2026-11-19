#!/usr/bin/env bash
# Check of the backups (INF-14), against the running stack:
# - the backup service runs, is healthy (its heartbeat), and has BACKUP_KEEP = 7 and
#   BACKUP_MAX_AGE_DAYS = 7;
# - catch-up at start: the service logged its decision since it started (and ran the backup
#   when it was due), and the decision on a test directory: no copy or a newest copy of
#   2 days ago -> due, a newest copy of 1 hour ago -> not due;
# - `make backup` writes a copy; result=ok in its status;
# - the newest dump reads to the end (pg_restore) and lists every app table of the database;
# - the newest files copy has as many files as the bucket has objects, and one object (the
#   first by name) has the same sha256 in the copy and in the bucket;
# - retention on a test directory inside the container, each kind (db, files) on its own:
#   fake copies 1, 3, 6, 8 and 12 days old plus 9 from the last 90 minutes -> only the 7
#   newest remain, none older than 7 days; the five aged copies alone -> those of 1, 3 and
#   6 days remain (age rule alone); a .partial of two days ago is gone, a fresh one stays (a
#   run may be writing it). The result is compared with the decided 7 days and 7 copies,
#   not with the service's own settings;
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
# The retention decided by the PO: at most 7 copies of each kind, none older than 7 days
# (Privacy Policy section 6: backups are kept for at most 7 days).
DECIDED_KEEP=7
DECIDED_MAX_AGE_DAYS=7

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
    in_backup rm -rf /tmp/retention-check /tmp/catch-up-check >/dev/null 2>&1 || true
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
max_age="$(in_backup printenv BACKUP_MAX_AGE_DAYS || true)"
if [ "$max_age" = "$DECIDED_MAX_AGE_DAYS" ]; then
    pass "BACKUP_MAX_AGE_DAYS = $max_age (decided: $DECIDED_MAX_AGE_DAYS)"
else
    fail "BACKUP_MAX_AGE_DAYS = ${max_age:-unset}, decided: $DECIDED_MAX_AGE_DAYS"
fi
pass "BACKUP_TIME = $(in_backup printenv BACKUP_TIME || true) in TZ $(in_backup printenv TZ || true)"
user="$(docker inspect -f '{{.Config.User}}' "$cid")"
if [ -n "$user" ] && [ "${user%%:*}" != 0 ] && [ "${user%%:*}" != root ]; then
    pass "runs as user $user, not root"
else
    fail "runs as user '${user:-root}', expected a non-root user"
fi

echo "Catch-up at start:"
started="$(docker inspect -f '{{.State.StartedAt}}' "$cid")"
docker logs --since "$started" "$cid" > "$work/start.log" 2>&1 || true
decision="$(grep -E ' backup: catch-up: (due|not due):' "$work/start.log" | sed -n 1p || true)"
decision="${decision#* backup: catch-up: }"
case "$decision" in
    due:*)
        caught_up="$(grep -E ' backup: start \(catch-up\), copy ' "$work/start.log" | sed -n 1p || true)"
        if [ -n "$caught_up" ]; then
            pass "since the start (${started%.*}Z): ${decision%%; one backup now}; ran ${caught_up#* backup: }"
        else
            fail "since the start (${started%.*}Z): $decision, but no 'start (catch-up)' line in the log"
        fi
        ;;
    "not due:"*) pass "since the start (${started%.*}Z): $decision, no backup at start" ;;
    *) fail "no catch-up decision in the log since the start (${started%.*}Z); expected 'catch-up: due' or 'catch-up: not due'" ;;
esac
# The decision on a test directory: none, then a newest copy of 2 days ago, then one of 1 hour ago.
catch_up_case() {
    in_backup bash -c '
        set -e
        root=/tmp/catch-up-check
        now=$(date +%s)
        for age in "$@"; do
            ts="$(date -u -d "@$((now - age))" +%Y%m%dT%H%M%SZ)"
            echo fake > "$root/db/db-$ts.dump"
        done
        backup.sh catch-up-check "$root"
    ' sh "$@"
}
in_backup bash -c 'rm -rf /tmp/catch-up-check && mkdir -p /tmp/catch-up-check/db /tmp/catch-up-check/files'
for case_ in "none:due" "172800:due" "3600:not due"; do
    ages="${case_%%:*}"
    want="${case_#*:}"
    if [ "$ages" = none ]; then
        label="no database copy"
        got="$(catch_up_case || true)"
    else
        label="newest database copy $((ages / 3600)) h old"
        got="$(catch_up_case "$ages" || true)"
    fi
    if [ "${got%%:*}" = "$want" ]; then
        pass "test directory, $label: $got"
    else
        fail "test directory, $label: ${got:-no answer}, expected $want"
    fi
done

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

echo "Retention (test directories /tmp/retention-check/a and b in the container):"
# a: fake copies 1, 3, 6, 8 and 12 days old plus 9 from the last 90 minutes (every 10
#    minutes), an old and a fresh .partial; b: the five aged copies alone. The same for db
#    and files. Prints "aged <days> <ts>" / "fresh <n> <ts>" for the comparison below.
in_backup bash -c '
    set -e
    now=$(date +%s)
    rm -rf /tmp/retention-check
    for set_ in a b; do mkdir -p "/tmp/retention-check/$set_/db" "/tmp/retention-check/$set_/files"; done
    copy() {
        echo fake > "$1/db/db-$2.dump"
        mkdir "$1/files/files-$2"
        echo fake > "$1/files/files-$2/object.txt"
    }
    for days in 1 3 6 8 12; do
        ts="$(date -u -d "@$((now - days * 86400))" +%Y%m%dT%H%M%SZ)"
        copy /tmp/retention-check/a "$ts"
        copy /tmp/retention-check/b "$ts"
        echo "aged $days $ts"
    done
    for n in 1 2 3 4 5 6 7 8 9; do
        ts="$(date -u -d "@$((now - n * 600))" +%Y%m%dT%H%M%SZ)"
        copy /tmp/retention-check/a "$ts"
        echo "fresh $n $ts"
    done
    root=/tmp/retention-check/a
    echo fake > "$root/db/db-19990101T000000Z.dump.partial"
    mkdir "$root/files/files-19990101T000000Z.partial"
    touch -d "2 days ago" "$root/db/db-19990101T000000Z.dump.partial" "$root/files/files-19990101T000000Z.partial"
    echo fake > "$root/db/db-20991231T000000Z.dump.partial"
    mkdir "$root/files/files-20991231T000000Z.partial"
' > "$work/fakes.txt"
for set_ in a b; do
    in_backup backup.sh retention "/tmp/retention-check/$set_" | sed 's/^/        /'
done
# Expected, from the decided values: a keeps the newest DECIDED_KEEP of the copies at most
# DECIDED_MAX_AGE_DAYS old; b keeps the aged copies at most DECIDED_MAX_AGE_DAYS old.
expect_a="$(awk -v max="$DECIDED_MAX_AGE_DAYS" '$1 == "fresh" || ($1 == "aged" && $2 <= max) { print $3 }' "$work/fakes.txt" | sort -r | sed -n "1,${DECIDED_KEEP}p" | sort)"
expect_b="$(awk -v max="$DECIDED_MAX_AGE_DAYS" '$1 == "aged" && $2 <= max { print $3 }' "$work/fakes.txt" | sort)"
# kept SET KIND: the timestamps of the complete copies left, oldest first.
kept() {
    local re
    if [ "$2" = db ]; then re='^db-([0-9]{8}T[0-9]{6}Z)\.dump$'; else re='^files-([0-9]{8}T[0-9]{6}Z)$'; fi
    in_backup sh -c "ls -1 /tmp/retention-check/$1/$2" | sed -n -E "s/$re/\\1/p" | sort
}
# labels: the timestamps on stdin as ages (12d, 30min), comma-separated.
labels() {
    awk 'NR == FNR { lab[$3] = ($1 == "aged") ? $2 "d" : ($2 * 10) "min"; next }
         { printf "%s%s", sep, (($1 in lab) ? lab[$1] : $1); sep = ", " } END { print "" }' "$work/fakes.txt" -
}
for kind in db files; do
    if [ "$kind" = db ]; then what="database copies"; else what="files copies"; fi
    got="$(kept a "$kind")"
    if [ -n "$got" ] && [ "$got" = "$expect_a" ]; then
        pass "$what, 1/3/6/8/12 days + 9 fresh: 14 -> $(printf '%s\n' "$got" | wc -l | tr -d ' ') ($(labels <<<"$got")), the newest $DECIDED_KEEP, none older than $DECIDED_MAX_AGE_DAYS days"
    else
        fail "$what, 1/3/6/8/12 days + 9 fresh: left ${got:+$(labels <<<"$got")}, expected $(labels <<<"$expect_a")"
    fi
    got="$(kept b "$kind")"
    if [ -n "$got" ] && [ "$got" = "$expect_b" ]; then
        pass "$what, 1/3/6/8/12 days alone: left $(labels <<<"$got") (age rule: none older than $DECIDED_MAX_AGE_DAYS days)"
    else
        fail "$what, 1/3/6/8/12 days alone: left ${got:+$(labels <<<"$got")}, expected $(labels <<<"$expect_b") (none older than $DECIDED_MAX_AGE_DAYS days)"
    fi
done
listing="$(in_backup sh -c 'cd /tmp/retention-check/a && ls -1 db files')"
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
