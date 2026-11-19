#!/usr/bin/env bash
# backup service (INF-14, INF-15): daily copies of the app database and of the bucket, kept
# on the named volume `backups` (mounted at /backups), and the restore steps that read them.
# Runs as a non-root user in the image built from infra/backup/Dockerfile (the db image,
# so pg_dump and pg_restore match the server's major version, plus the mc client of the
# MinIO image). See docs/disaster-recovery.md.
#
#   backup.sh loop            default command: one backup a day at BACKUP_TIME (TZ), none at start
#   backup.sh run             one backup now (`make backup`); exits 1 when it failed
#   backup.sh status          the last run and the next scheduled one
#   backup.sh list            the complete copies, newest first
#   backup.sh resolve <ts|latest>   the timestamp of a complete pair (database and files)
#   backup.sh verify-db <file>      the checks a new dump must pass before it is kept
#   backup.sh retention <dir>       retention on <dir> (db/ and files/ below it), for tests
#   backup.sh restore-db <ts>       pg_restore into POSTGRES_DB (the api must be stopped)
#   backup.sh restore-files <ts>    mirror a files copy back into the bucket
#   backup.sh mc <args>             mc with the alias `store` (the MinIO server) set
#
# Layout of /backups (no file or directory name carries the project name):
#   db/db-<UTC yyyymmddThhmmssZ>.dump      pg_dump -Fc of POSTGRES_DB only
#   files/files-<same timestamp>/          mc mirror of the bucket, a full copy per run
#   status                                 the last run: time, result, sizes
# Every copy is written under a .partial name first and renamed only once verified.
#
# Credentials come from the container environment that compose sets (PGPASSWORD,
# MINIO_ROOT_*), as for the other services until INF-13 moves them to Vault. They never
# appear on a command line or in the output.
set -euo pipefail

BACKUP_DIR=/backups
BACKUP_TIME="${BACKUP_TIME:-03:00}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
# Touched every minute by the loop; the health check wants it younger than 3 minutes.
HEARTBEAT=/tmp/heartbeat
NEXT_RUN_FILE=/tmp/next-run
# One backup or restore at a time: a `make backup` during the scheduled run waits for it.
LOCK=/tmp/backup.lock
LOCK_WAIT_SEC=3600
# A .partial older than this is a leftover of an interrupted run (a run takes minutes).
PARTIAL_MAX_AGE_MIN=1440
DB_NAME_RE='^db-[0-9]{8}T[0-9]{6}Z\.dump$'
FILES_NAME_RE='^files-[0-9]{8}T[0-9]{6}Z$'
TS_RE='^[0-9]{8}T[0-9]{6}Z$'

: "${PGHOST:?}" "${PGUSER:?}" "${PGPASSWORD:?}" "${PGDATABASE:?}"
: "${MINIO_ROOT_USER:?}" "${MINIO_ROOT_PASSWORD:?}" "${MINIO_BUCKET:?}"

# mc reads the alias from the environment, as in infra/minio/init-bucket.sh: the
# credentials stay out of argv, config files and output (init-env.sh generates URL-safe hex).
export MC_HOST_store="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000"
export MC_CONFIG_DIR=/tmp/.mc
BUCKET="store/$MINIO_BUCKET"

log() { printf '%s backup: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$*"; }
die() { log "error: $*" >&2; exit 1; }

valid_keep() { [[ "$BACKUP_KEEP" =~ ^[1-9][0-9]*$ ]] || die "BACKUP_KEEP=$BACKUP_KEEP is not a whole number of 1 or more"; }
valid_time() { [[ "$BACKUP_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || die "BACKUP_TIME=$BACKUP_TIME is not HH:MM (00:00 to 23:59)"; }

take_lock() {
    exec 9>"$LOCK"
    if ! flock -n 9; then
        log "another backup or restore is running; waiting for it (up to ${LOCK_WAIT_SEC}s)"
        flock -w "$LOCK_WAIT_SEC" 9 || die "still locked after ${LOCK_WAIT_SEC}s"
    fi
}

human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "$1 bytes"; }
bytes() { du -sb "$1" | cut -f1; }

# Tables of the app in schema public, without the ones an extension owns (PostGIS's
# spatial_ref_sys): what a dump of POSTGRES_DB must contain.
app_tables() {
    psql -X -q -A -t -v ON_ERROR_STOP=1 -c "
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                          AND d.objid = c.oid AND d.deptype = 'e')
        ORDER BY 1"
}

# verify_dump FILE [TABLE...]: the archive's table of contents reads (pg_restore --list)
# and names every TABLE given (the current app tables when none is given), and the whole
# archive reads to the end (pg_restore to /dev/null). The table of contents sits at the
# start of the file, so --list alone still passes on a dump that lost its last bytes
# (tested: 100 bytes cut, --list exit 0); reading every data block catches that. Prints the
# reason and returns 1 on the first failure.
verify_dump() {
    local file="$1" toc missing="" table
    shift
    local tables=("$@")
    if [ "${#tables[@]}" -eq 0 ]; then
        mapfile -t tables < <(app_tables)
    fi
    [ "${#tables[@]}" -gt 0 ] || { echo "no app table in $PGDATABASE to compare with"; return 1; }
    [ -s "$file" ] || { echo "$file is missing or empty"; return 1; }
    toc="$(pg_restore --list "$file" 2>&1)" || { echo "pg_restore --list failed: ${toc##*$'\n'}"; return 1; }
    for table in "${tables[@]}"; do
        grep -Eq "^[0-9]+; [0-9]+ [0-9]+ TABLE public $table( |\$)" <<<"$toc" || missing="$missing $table"
    done
    [ -z "$missing" ] || { echo "tables missing from the dump:$missing"; return 1; }
    local err
    err="$(pg_restore --file=/dev/null "$file" 2>&1)" || { echo "the archive does not read to the end: ${err##*$'\n'}"; return 1; }
    echo "${#tables[@]} app tables listed, archive reads to the end"
}

bucket_count() { mc ls --recursive "$BUCKET" | wc -l; }
copy_count() { find "$1" -type f | wc -l; }

# prune DIR REGEX TYPE KEEP: removes the oldest complete copies in DIR beyond KEEP. The
# timestamp in the name orders them (UTC, fixed width), so a copied or touched file keeps
# its place.
prune() {
    local dir="$1" regex="$2" type="$3" keep="$4" names excess i
    [ -d "$dir" ] || return 0
    mapfile -t names < <(find "$dir" -mindepth 1 -maxdepth 1 -type "$type" -printf '%f\n' | grep -E "$regex" | sort)
    excess=$((${#names[@]} - keep))
    for ((i = 0; i < excess; i++)); do
        rm -rf -- "${dir:?}/${names[i]}"
        log "retention: removed ${dir##*/}/${names[i]}"
    done
}

# retention ROOT: keeps the newest BACKUP_KEEP complete copies of each kind under ROOT/db
# and ROOT/files, and removes .partial leftovers older than a day (a younger one may belong
# to a run in progress).
retention() {
    local root="$1" dir
    valid_keep
    prune "$root/db" "$DB_NAME_RE" f "$BACKUP_KEEP"
    prune "$root/files" "$FILES_NAME_RE" d "$BACKUP_KEEP"
    for dir in "$root/db" "$root/files"; do
        [ -d "$dir" ] || continue
        while IFS= read -r stale; do
            rm -rf -- "$stale"
            log "retention: removed leftover ${stale#"$root"/}"
        done < <(find "$dir" -mindepth 1 -maxdepth 1 -name '*.partial' -mmin +"$PARTIAL_MAX_AGE_MIN")
    done
}

count_copies() { find "$BACKUP_DIR/$1" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | grep -Ec "$2" || true; }

write_status() {
    local tmp="$BACKUP_DIR/.status.tmp"
    printf '%s\n' "$@" > "$tmp"
    mv "$tmp" "$BACKUP_DIR/status"
}

# backup_db TS: dump, verify, rename. Sets db_line; returns 1 with db_line as the reason.
backup_db() {
    local ts="$1" part final tables reason
    final="$BACKUP_DIR/db/db-$ts.dump"
    part="$final.partial"
    mapfile -t tables < <(app_tables) || { db_line="cannot list the app tables of $PGDATABASE"; return 1; }
    if ! reason="$(pg_dump --format=custom --file="$part" 2>&1)"; then
        rm -f "$part"
        db_line="pg_dump failed: ${reason##*$'\n'}"
        return 1
    fi
    if ! reason="$(verify_dump "$part" "${tables[@]}")"; then
        db_line="dump kept as ${part#"$BACKUP_DIR"/}, not verified: $reason"
        return 1
    fi
    mv "$part" "$final"
    db_size="$(bytes "$final")"
    db_line="db/db-$ts.dump ($(human "$db_size"), $reason)"
}

# backup_files TS: mirror, compare the object count, rename. Sets files_line.
backup_files() {
    local ts="$1" part final want got attempt reason
    final="$BACKUP_DIR/files/files-$ts"
    part="$final.partial"
    mkdir -p "$part"
    # A second pass when the count differs: an upload or delete during the first pass.
    for attempt in 1 2; do
        if ! reason="$(mc mirror --quiet --overwrite --remove "$BUCKET" "$part" 2>&1)"; then
            files_line="mc mirror failed: ${reason##*$'\n'}"
            return 1
        fi
        want="$(bucket_count)" || { files_line="cannot list the bucket"; return 1; }
        got="$(copy_count "$part")"
        [ "$got" = "$want" ] && break
    done
    if [ "$got" != "$want" ]; then
        files_line="copy kept as ${part#"$BACKUP_DIR"/}, not verified: $got files, the bucket has $want objects"
        return 1
    fi
    mv "$part" "$final"
    files_size="$(bytes "$final")"
    files_line="files/files-$ts/ ($got objects, $(human "$files_size"), same count as the bucket)"
}

# run_backup REASON: one database dump and one files copy under the same timestamp, then
# retention and the status file. Returns 1 when either copy failed.
run_backup() {
    local why="$1" ts started start_epoch result=ok db_line files_line db_size=0 files_size=0
    take_lock
    mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/files"
    ts="$(date -u +%Y%m%dT%H%M%SZ)"
    # Two runs in the same second would share a name.
    while [ -e "$BACKUP_DIR/db/db-$ts.dump" ] || [ -e "$BACKUP_DIR/files/files-$ts" ]; do
        sleep 1
        ts="$(date -u +%Y%m%dT%H%M%SZ)"
    done
    started="$(date '+%Y-%m-%d %H:%M:%S %z')"
    start_epoch="$(date +%s)"
    log "start ($why), copy $ts"
    backup_db "$ts" || result=FAIL
    log "database: $db_line"
    backup_files "$ts" || result=FAIL
    log "files: $files_line"
    retention "$BACKUP_DIR"
    write_status \
        "last_run=$started ($why)" \
        "result=$result" \
        "copy=$ts" \
        "db=$db_line" \
        "files=$files_line" \
        "duration=$(($(date +%s) - start_epoch))s" \
        "kept=$(count_copies db "$DB_NAME_RE") database copies, $(count_copies files "$FILES_NAME_RE") files copies (BACKUP_KEEP=$BACKUP_KEEP)"
    log "done ($result) in $(($(date +%s) - start_epoch))s"
    [ "$result" = ok ]
}

status() {
    if [ -f "$BACKUP_DIR/status" ]; then
        cat "$BACKUP_DIR/status"
    else
        echo "last_run=none yet"
    fi
    if [ -f "$NEXT_RUN_FILE" ]; then
        echo "next_run=$(date -d "@$(cat "$NEXT_RUN_FILE")" '+%Y-%m-%d %H:%M %z') (BACKUP_TIME=$BACKUP_TIME, TZ=${TZ:-UTC})"
    fi
}

# Complete pairs (a database dump and a files copy with the same timestamp), newest first.
pairs() {
    local name ts
    find "$BACKUP_DIR/db" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | grep -E "$DB_NAME_RE" | sort -r |
        while IFS= read -r name; do
            ts="${name#db-}"
            ts="${ts%.dump}"
            if [ -d "$BACKUP_DIR/files/files-$ts" ]; then echo "$ts"; fi
        done
}

list() {
    local ts any=no
    while IFS= read -r ts; do
        any=yes
        printf '%s  db %s  files %s objects, %s\n' "$ts" \
            "$(human "$(bytes "$BACKUP_DIR/db/db-$ts.dump")")" \
            "$(copy_count "$BACKUP_DIR/files/files-$ts")" \
            "$(human "$(bytes "$BACKUP_DIR/files/files-$ts")")"
    done < <(pairs)
    [ "$any" = yes ] || echo "no complete copy in $BACKUP_DIR"
}

# resolve ARG: latest, a timestamp, or a dump name (db-<ts>.dump); prints the timestamp of
# a complete pair or fails.
resolve() {
    local arg="$1" ts
    case "$arg" in
        latest) ts="$(pairs | sed -n 1p)" ;;
        *) ts="${arg##*/}"; ts="${ts#db-}"; ts="${ts#files-}"; ts="${ts%.dump}" ;;
    esac
    [ -n "$ts" ] || die "no complete copy (database and files) in $BACKUP_DIR"
    [[ "$ts" =~ $TS_RE ]] || die "BACKUP=$arg: expected latest or a timestamp such as 20261119T230000Z (make backup-list)"
    [ -f "$BACKUP_DIR/db/db-$ts.dump" ] || die "no database copy db/db-$ts.dump"
    [ -d "$BACKUP_DIR/files/files-$ts" ] || die "no files copy files/files-$ts/ for that database copy"
    echo "$ts"
}

restore_db() {
    local ts file reason
    ts="$(resolve "$1")"
    file="$BACKUP_DIR/db/db-$ts.dump"
    take_lock
    # Only the archive itself: the database being replaced may be empty.
    reason="$(pg_restore --list "$file" 2>&1 >/dev/null)" || die "db/db-$ts.dump does not read: $reason"
    log "restore: database $PGDATABASE from db/db-$ts.dump"
    # --clean --if-exists: drops each object of the dump that exists, then recreates it, so
    # this works on the old database and on the empty one the db image creates on a new
    # volume (PostGIS extensions included). --no-owner: the objects belong to PGUSER.
    # --single-transaction: all or nothing; the first error rolls everything back.
    pg_restore --clean --if-exists --no-owner --single-transaction --dbname="$PGDATABASE" "$file"
    local postgis users
    postgis="$(psql -X -A -t -v ON_ERROR_STOP=1 -c "SELECT extversion FROM pg_extension WHERE extname = 'postgis'")"
    [ -n "$postgis" ] || die "restore: the postgis extension is missing after the restore"
    users="$(psql -X -A -t -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM users')"
    log "restore: database done: $(app_tables | wc -l) app tables, $users users, PostGIS $postgis, alembic $(psql -X -A -t -c 'SELECT version_num FROM alembic_version')"
}

restore_files() {
    local ts src want got
    ts="$(resolve "$1")"
    src="$BACKUP_DIR/files/files-$ts"
    take_lock
    mc ready store >/dev/null 2>&1 || die "MinIO is not ready"
    mc stat "$BUCKET" >/dev/null 2>&1 || die "bucket $MINIO_BUCKET missing; minio-init creates it"
    log "restore: bucket $MINIO_BUCKET from files/files-$ts/"
    # --remove: objects that are not in the copy go, so the bucket matches the database of
    # the same moment (no file without its row, no row without its file).
    mc mirror --quiet --overwrite --remove "$src" "$BUCKET"
    want="$(copy_count "$src")"
    got="$(bucket_count)"
    [ "$got" = "$want" ] || die "restore: the bucket has $got objects, the copy $want"
    log "restore: bucket done: $got objects"
}

loop() {
    local next now wait
    valid_time
    valid_keep
    trap 'log "stopping"; exit 0' TERM INT
    mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/files"
    log "one backup a day at $BACKUP_TIME (TZ=${TZ:-UTC}), keeping $BACKUP_KEEP copies; no backup at start"
    next="$(next_run)"
    while true; do
        touch "$HEARTBEAT"
        now="$(date +%s)"
        if [ "$now" -ge "$next" ]; then
            run_backup scheduled || log "the scheduled backup failed; see the lines above and status"
            next="$(next_run)"
            touch "$HEARTBEAT"
            now="$(date +%s)"
        fi
        wait=$((next - now))
        if [ "$wait" -gt 60 ]; then wait=60; fi
        # In the background, so that docker stop (SIGTERM) ends the wait at once.
        sleep "$wait" &
        wait $! || true
    done
}

# The next BACKUP_TIME after now, in TZ; also written for `status`.
next_run() {
    local t
    t="$(date -d "today $BACKUP_TIME" +%s)"
    if [ "$t" -le "$(date +%s)" ]; then
        t="$(date -d "tomorrow $BACKUP_TIME" +%s)"
    fi
    echo "$t" > "$NEXT_RUN_FILE"
    log "next backup: $(date -d "@$t" '+%Y-%m-%d %H:%M %z')" >&2
    echo "$t"
}

command="${1:-loop}"
shift || true
case "$command" in
    loop) loop ;;
    run)
        if run_backup manual; then status; else status; exit 1; fi
        ;;
    status) status ;;
    list) list ;;
    resolve) resolve "${1:?resolve needs latest or a timestamp}" ;;
    verify-db) verify_dump "${1:?verify-db needs a file}" ;;
    retention) retention "${1:?retention needs a directory}" ;;
    restore-db) restore_db "${1:?restore-db needs latest or a timestamp}" ;;
    restore-files) restore_files "${1:?restore-files needs latest or a timestamp}" ;;
    mc) exec mc "$@" ;;
    *) die "unknown command $command (loop, run, status, list, resolve, verify-db, retention, restore-db, restore-files, mc)" ;;
esac
