#!/usr/bin/env bash
# Smoke test of monitoring (INF-08, module M12), against the running stack:
# - every active scrape target in Prometheus is up, and each of the jobs prometheus, api,
#   postgres, redis and cadvisor has one; only a scrape after the check started counts, so
#   a target stopped a few seconds before does not pass on its last result;
# - one real series per source: pg_up == 1 (postgres-exporter reaches the database),
#   redis_up == 1 (redis-exporter reaches Redis), a container CPU and a memory series of the
#   api service (cAdvisor), an HTTP request counter of the API (BE-30);
# - Prometheus runs with the retention decided by the PO: 30d and 1GB.
# Prometheus has no host port and no proxy route, so every query runs inside its own
# container (`docker compose exec -T prometheus wget ...`); the answers are parsed here with
# python3 (3.9 or newer). Retries for up to 60 s (a fresh stack needs a scrape or two; a
# run on a healthy stack takes one scrape interval, about 15 s), then prints one ok / FAIL
# line per check and exits 1 when one failed.
# Needs the stack up (`make`). Run it with `make metrics-check`. Works with bash 3.2 (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
WAIT_SEC=60
RETRY_SEC=5
PROM=http://127.0.0.1:9090

if [ -z "$(docker compose ps -q --status running prometheus)" ]; then
    echo "metrics-check: prometheus is not running; start the stack with make" >&2
    exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Instant queries: file name, then PromQL. Series are selected by the compose service label,
# never by the compose project.
QUERIES=(
    "pg_up|pg_up"
    "redis_up|redis_up"
    "api_cpu|container_cpu_usage_seconds_total{container_label_com_docker_compose_service=\"api\"}"
    "api_memory|container_memory_working_set_bytes{container_label_com_docker_compose_service=\"api\"}"
    "api_requests|sum(http_requests_total{job=\"api\"})"
)

# prom_get PATH FILE: one GET on the Prometheus HTTP API from inside its container; an
# empty FILE when it does not answer.
prom_get() {
    docker compose exec -T prometheus wget -qO- "$PROM$1" >"$work/$2" 2>/dev/null || : >"$work/$2"
}

urlencode() {
    python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

fetch_all() {
    local entry
    prom_get "/api/v1/targets?state=active" targets.json
    prom_get "/api/v1/status/flags" flags.json
    for entry in "${QUERIES[@]}"; do
        prom_get "/api/v1/query?query=$(urlencode "${entry#*|}")" "${entry%%|*}.json"
    done
}

# Prints one "ok    ..." or "FAIL  ..." line per check from the files in $work.
evaluate() {
    python3 - "$work" "$started" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

work = Path(sys.argv[1])
started = float(sys.argv[2])
JOBS = ["prometheus", "api", "postgres", "redis", "cadvisor"]


def epoch(rfc3339):
    """Seconds since 1970 of a Go RFC 3339 time such as 2026-11-15T08:06:45.198669052Z."""
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)", rfc3339 or "")
    if not match:
        return 0.0
    base = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    offset = 0 if match.group(3) == "Z" else int(match.group(3)[1:3]) * 3600 + int(match.group(3)[4:]) * 60
    sign = -1 if match.group(3).startswith("+") else 1
    return base.timestamp() + float(match.group(2) or 0) + sign * offset


RETENTION ={"storage.tsdb.retention.time": "30d", "storage.tsdb.retention.size": "1GB"}


def load(name):
    """The data of a Prometheus API answer, or None when there is none."""
    try:
        answer = json.loads((work / name).read_text())
    except (OSError, ValueError):
        return None
    return answer.get("data") if answer.get("status") == "success" else None


def line(ok, text):
    print(f"{'ok  ' if ok else 'FAIL'}  {text}")


targets = load("targets.json")
if targets is None:
    line(False, "targets: no answer from /api/v1/targets")
else:
    active = targets.get("activeTargets", [])
    for job in JOBS:
        mine = [t for t in active if t.get("labels", {}).get("job") == job]
        down = [t for t in mine if t.get("health") != "up"]
        # Health is the result of the last scrape, up to 15 s old: a target stopped just
        # before the check would still read "up". Only a scrape after the start counts.
        old = [t for t in mine if epoch(t.get("lastScrape")) <= started]
        if not mine:
            line(False, f"target {job}: no such scrape target")
        elif old:
            line(False, f"target {job}: no scrape since the check started")
        elif down:
            t = down[0]
            line(False, f"target {job}: {t.get('scrapeUrl')} is {t.get('health')}"
                        f" ({t.get('lastError') or 'no scrape yet'})")
        else:
            line(True, f"target {job}: up ({mine[0].get('scrapeUrl')})")
    not_up = [t for t in active if t.get("health") != "up"]
    line(not not_up and bool(active),
         f"every target up: {len(active) - len(not_up)} of {len(active)}")


def series(name):
    data = load(f"{name}.json")
    return None if data is None else data.get("result", [])


def single_value(name, query, expected=None, positive=False):
    result = series(name)
    if result is None:
        line(False, f"{query}: no answer from /api/v1/query")
    elif not result:
        line(False, f"{query}: no series")
    else:
        values = [float(r["value"][1]) for r in result]
        if expected is not None:
            line(all(v == expected for v in values),
                 f"{query} == {expected:g}: {', '.join(f'{v:g}' for v in values)}")
        elif positive:
            line(all(v > 0 for v in values), f"{query} > 0: {', '.join(f'{v:g}' for v in values)}")


def has_series(name, what):
    result = series(name)
    if result is None:
        line(False, f"{what}: no answer from /api/v1/query")
    else:
        line(bool(result), f"{what}: {len(result)} series")


single_value("pg_up", "pg_up", expected=1)
single_value("redis_up", "redis_up", expected=1)
has_series("api_cpu", "container CPU of the api service (cAdvisor)")
has_series("api_memory", "container memory of the api service (cAdvisor)")
single_value("api_requests", "sum(http_requests_total{job=\"api\"})", positive=True)

# Prometheus prints the parsed flag, not the text it was given: 1GB comes back as 1GiB
# (its size units are powers of 2, so the two are the same) and 7d as 1w. Compare values.
SIZE_UNITS = {"B": 0, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5, "E": 6}
TIME_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}


def size_bytes(text):
    match = re.fullmatch(r"(\d+)([BKMGTPE])(i?B)?", text or "")
    if not match or (match.group(2) == "B" and match.group(3)):
        return None
    return int(match.group(1)) * 1024 ** SIZE_UNITS[match.group(2)]


def duration_seconds(text):
    parts = re.findall(r"(\d+)(ms|[smhdwy])", text or "")
    if not parts or "".join(n + u for n, u in parts) != text:
        return None
    return sum(int(n) * TIME_UNITS[u] for n, u in parts)


PARSE = {"storage.tsdb.retention.time": duration_seconds, "storage.tsdb.retention.size": size_bytes}
flags = load("flags.json")
for flag, expected in RETENTION.items():
    if flags is None:
        line(False, f"--{flag}: no answer from /api/v1/status/flags")
    else:
        actual = flags.get(flag)
        parse = PARSE[flag]
        line(parse(actual) is not None and parse(actual) == parse(expected),
             f"--{flag}={actual} (decided: {expected})")
PY
}

# Prometheus's own clock, so that "scraped since the start" does not depend on the host's.
prom_get "/api/v1/query?query=$(urlencode 'time()')" start.json
if ! started="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["data"]["result"][1])' \
    "$work/start.json" 2>/dev/null)"; then
    echo "metrics-check: no answer from Prometheus at $PROM inside its container" >&2
    exit 1
fi

deadline=$(($(date +%s) + WAIT_SEC))
while :; do
    fetch_all
    evaluate >"$work/result"
    failures="$(grep -c '^FAIL' "$work/result" || true)"
    if [ "$failures" = 0 ] || [ "$(date +%s)" -ge "$deadline" ]; then
        break
    fi
    echo "metrics-check: $failures checks not ok yet, retrying in ${RETRY_SEC}s"
    sleep "$RETRY_SEC"
done

sed 's/^/  /' "$work/result"
if [ "$failures" != 0 ]; then
    echo "metrics-check: $failures checks failed"
    exit 1
fi
echo "metrics-check: all checks passed"
