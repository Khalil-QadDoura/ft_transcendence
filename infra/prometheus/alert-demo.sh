#!/usr/bin/env bash
# Live alert demo (INF-10, module M12), against the running stack; manual only, not in CI:
# 1. `docker compose stop redis`;
# 2. polls Prometheus' /api/v1/alerts every 5 s until RedisDown is firing, printing when it
#    turns pending and when it fires, in seconds since the stop; fails after 120 s;
# 3. `docker compose up -d --wait redis`;
# 4. polls until RedisDown is gone (resolved), printing the seconds since Redis was started
#    again; fails after 120 s;
# 5. prints ok.
# redis-exporter stays up while Redis is stopped and reports redis_up 0, so RedisDown
# (redis_up == 0 for 30 s, infra/prometheus/alerts.yml) fires: one scrape (at most 15 s) +
# one evaluation (at most 15 s) + 30 s = about 45 to 75 s. While it fires, the "Firing
# alerts" panel of the WOZU Infrastructure dashboard goes up by one and Grafana's
# Alerting > Alert rules page shows RedisDown as firing.
# Redis is started again whenever the script ends after stopping it (failure or Ctrl-C
# included), so the stack is never left without Redis.
# Prometheus has no host port, so it is asked inside its container, as metrics-check does.
# Run it with `make alert-demo`. Works with bash 3.2 (macOS) and python3 3.9 or newer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ALERT=RedisDown
LIMIT_SEC=120
POLL_SEC=5
PROM=http://127.0.0.1:9090

for service in prometheus redis redis-exporter; do
    if [ -z "$(docker compose ps -q --status running "$service")" ]; then
        echo "alert-demo: $service is not running; start the stack with make" >&2
        exit 1
    fi
done

# state: RedisDown's state in /api/v1/alerts: firing, pending, none, or "error" when
# Prometheus does not answer.
state() {
    local answer
    answer="$(docker compose exec -T prometheus wget -qO- "$PROM/api/v1/alerts" 2>/dev/null)" || answer=""
    python3 -c '
import json, sys
try:
    alerts = json.load(sys.stdin)["data"]["alerts"]
except (ValueError, KeyError, TypeError):
    print("error")
    sys.exit()
states = {a.get("state") for a in alerts if a.get("labels", {}).get("alertname") == sys.argv[1]}
print("firing" if "firing" in states else "pending" if "pending" in states else "none")
' "$ALERT" <<<"$answer"
}

# wait_for WANTED SINCE: polls until the state is WANTED; prints each change with the
# seconds since SINCE; returns 1 after LIMIT_SEC.
wait_for() {
    local wanted="$1" since="$2" last="" now elapsed
    while :; do
        now="$(state)"
        elapsed=$(($(date +%s) - since))
        if [ "$now" != "$last" ]; then
            echo "alert-demo: ${elapsed}s: $ALERT $now"
            last="$now"
        fi
        if [ "$now" = "$wanted" ]; then
            return 0
        fi
        if [ "$elapsed" -ge "$LIMIT_SEC" ]; then
            echo "alert-demo: FAIL: $ALERT not $wanted after ${LIMIT_SEC}s" >&2
            return 1
        fi
        sleep "$POLL_SEC"
    done
}

before="$(state)"
if [ "$before" != none ]; then
    echo "alert-demo: $ALERT is already $before before the demo; is Redis up? (make)" >&2
    exit 1
fi

restart_redis() {
    echo "alert-demo: starting Redis again (docker compose up -d --wait redis)"
    docker compose up -d --wait redis
}
# From here on, Redis is started again however the script ends.
redis_stopped=0
trap 'status=$?; trap - EXIT; if [ "$redis_stopped" = 1 ]; then restart_redis || status=1; fi; exit "$status"' EXIT
trap 'exit 130' INT TERM
redis_stopped=1

echo "alert-demo: stopping Redis (docker compose stop redis); $ALERT should fire within about 75 s"
docker compose stop redis
stopped_at="$(date +%s)"
wait_for firing "$stopped_at"
fired=$(($(date +%s) - stopped_at))

restart_redis
redis_stopped=0
started_at="$(date +%s)"
wait_for none "$started_at"
resolved=$(($(date +%s) - started_at))

echo "alert-demo: ok: $ALERT fired ${fired}s after Redis stopped and resolved ${resolved}s after it started again"
