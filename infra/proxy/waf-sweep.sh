#!/usr/bin/env bash
# WAF sweep (INF-11): everyday text and random tokens through the proxy, where the browser
# sends them, counting the WAF's 403s (nginx's HTML page) with the rules that fired.
#
#   infra/proxy/waf-sweep.sh ci         the CI part of `make waf-check` (it runs this): the
#                                       "* " lines of waf-corpus.txt in every free-text field;
#                                       in each token field a value that was blocked before
#                                       the token blocks and a fresh one (must pass), and 4 or
#                                       5 probes (must get the WAF's 403); 3 attack probes in
#                                       every free-text field (must get the WAF's 403). About
#                                       1000 requests, under a minute.
#   infra/proxy/waf-sweep.sh corpus     every line of waf-corpus.txt in every free-text field
#   infra/proxy/waf-sweep.sh tokens [N] [M]
#                                       N values per token kind (default 2000), each made the
#                                       way the backend makes it, sent in every place it
#                                       travels; then M more per kind (default 200000) tested
#                                       offline against the running proxy's CRS regexes (PL1
#                                       and PL2 rules on ARGS and cookies), and every value that
#                                       matches one sent the same way. A rule hit about one
#                                       token in 8000 to 17000 per kind, too rare for N alone;
#                                       the offline test finds more than the WAF blocks (a
#                                       chained rule may skip the value), so only the WAF's
#                                       answer is counted. Then the CI token checks. About
#                                       3 minutes.
#   infra/proxy/waf-sweep.sh all [N] [M] corpus, then tokens
#   WAF_SWEEP=1 make waf-check          waf-check, then `all` (manual, not in CI)
#
# Requests carry a made-up Bearer token or none, so the API answers 401 or another JSON
# error and nothing is stored: the WAF reads the request before the API does, the same way
# whatever the answer. Every request has ?waf_sweep=<run>-<n>, so the audit line of a block
# is found by its URI and its rules are printed with their paranoia level.
# A 403 is accepted only for the sentences of ACCEPTED below (docs/infra/waf.md, "Known false
# positives"): each is matched by a paranoia level 1 rule, and PL1 rules are never lifted.
# Exits 1 on any other WAF 403 or on a probe that passes.
# Every API error is a 4xx the WAF audits: a full sweep writes about 10 MB of audit lines and
# 9 MB of access lines to `docker compose logs proxy` (rotated at 30 MB); `make logs-reset`
# clears them afterwards.
# Needs the stack up (`make`), Python 3.9+ (standard library only) and docker.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

mode="${1:-ci}"
case "$mode" in
    ci | corpus | tokens | all) ;;
    *) echo "usage: $0 [ci|corpus|tokens|all] [values per kind sent] [values per kind tested offline]" >&2; exit 2 ;;
esac
per_kind="${2:-2000}"
prescreen="${3:-200000}"

if [ -z "$(docker compose ps -q proxy)" ]; then
    echo "waf-sweep: the stack is not running; start it with make" >&2
    exit 1
fi
https_port="$(docker compose port proxy 8443)"
https_port="${https_port##*:}"

exec python3 -I - "$ROOT" "$https_port" "$mode" "$per_kind" "$prescreen" <<'PY'
import base64
import hashlib
import hmac
import http.client
import json
import multiprocessing
import os
import re
import secrets
import ssl
import string
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

ROOT, PORT, MODE = sys.argv[1], int(sys.argv[2]), sys.argv[3]
PER_KIND, PRESCREEN = int(sys.argv[4]), int(sys.argv[5])
CTX = ssl.create_default_context(cafile=os.path.join(ROOT, "infra/proxy/certs/server.crt"))
RUN = uuid.uuid4().hex[:10]
REPORT = os.environ.get("WAF_SWEEP_REPORT")  # optional: a JSON file with every block
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
THREADS = 8

# Every free-text field of the API, with the rest of a valid body around it.
# (label, method, path, "json" or "query", field, other fields)
FIELDS = []
for f in ("first_name", "last_name", "position", "bio"):
    FIELDS.append(("PATCH /api/users/me", "PATCH", "/api/users/me", "json", f, {}))
for f in ("name", "description", "country", "city", "district"):
    FIELDS.append(("POST /api/companies", "POST", "/api/companies", "json", f,
                   {"name": "Acme", "country": "United Arab Emirates", "city": "Abu Dhabi"}))
for f in ("name", "country", "city", "district"):
    FIELDS.append(("PATCH /api/companies/me", "PATCH", "/api/companies/me", "json", f,
                   {"name": "Acme", "country": "United Arab Emirates", "city": "Abu Dhabi",
                    "district": "Al Reem", "country_code": "AE"}))
JOB = {"title": "Cashier", "description": "Day shifts.", "latitude": 24.49, "longitude": 54.4,
       "location": "Abu Dhabi", "status": "draft", "salary_amount": 3000, "salary_type": "monthly",
       "salary_currency": "AED", "schedule": "full_time", "urgency": "normal"}
for f in ("title", "description", "location"):
    FIELDS.append(("POST /api/jobs", "POST", "/api/jobs", "json", f, JOB))
    FIELDS.append(("PATCH /api/jobs/<id>", "PATCH", "/api/jobs/41", "json", f, {}))
FIELDS.append(("POST /api/jobs/<id>/apply", "POST", "/api/jobs/41/apply", "json", "cover_note", {}))
FIELDS.append(("PATCH /api/applications/<id>/status", "PATCH", "/api/applications/7/status", "json",
               "note", {"status": "rejected"}))
FIELDS.append(("POST /api/conversations/<id>/messages", "POST", "/api/conversations/3/messages",
               "json", "content", {"idempotency_key": "IDEMPOTENCY"}))
FIELDS.append(("PATCH /api/conversations/<id>/messages/<id>", "PATCH",
               "/api/conversations/3/messages/12", "json", "content", {}))
for f in ("keyword", "position"):
    FIELDS.append(("GET /api/jobs/open", "GET", "/api/jobs/open", "query", f, {"limit": "20"}))
    # The jobs page keeps its filters in its own URL: a reload or a shared link sends them.
    FIELDS.append(("GET /jobs (page)", "GET", "/jobs", "query", f, {}))

PROBES = ["' OR 1=1 --", "<script>alert(1)</script>", "1 UNION SELECT password FROM users--"]

# Sentences the WAF blocks with a paranoia level 1 rule, which is never lifted; see
# docs/infra/waf.md, "Known false positives". {sentence: the PL1 rule ids that block it}.
# libinjection (942100) reads "! 10 or 11" and "Part-time iş --" as SQL.
ACCEPTED = {
    "Hi Мария! مرحبا 👋 See you at 10 or 11": ["942100"],
    "Part-time iş -- yalnız həftəsonu": ["942100"],
}


def corpus(subset):
    lines = []
    with open(os.path.join(ROOT, "infra/proxy/waf-corpus.txt"), encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            starred = line.startswith("* ")
            if subset and not starred:
                continue
            lines.append(line[2:] if starred else line)
    return lines


# ---------------------------------------------------------------- values as the backend makes them
def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def fake_jwt(scope, lifetime, ver=True):
    """An HS256 JWT shaped as auth/security.py create_token makes it (PyJWT, compact JSON),
    signed with a throwaway key: the API refuses it, the WAF sees the same characters."""
    now = int(time.time()) - secrets.randbelow(86400)
    claims = {"sub": str(1 + secrets.randbelow(5000)), "scope": scope, "jti": uuid.uuid4().hex,
              "iat": now, "exp": now + int(lifetime.total_seconds())}
    if ver:
        claims["ver"] = secrets.randbelow(6)
    head = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(secrets.token_bytes(32), ("%s.%s" % (head, body)).encode(), hashlib.sha256).digest()
    return "%s.%s.%s" % (head, body, b64url(sig))


def pm_password():
    """A password-manager password with symbols (the password fields have every CRS rule
    lifted, 10030-10033, so it does not matter to the count)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{};:,.<>/?~"
    return "".join(secrets.choice(alphabet) for _ in range(24))


BEARER = "Bearer " + fake_jwt("access", timedelta(minutes=15))


def token_requests(kind, value):
    """Every place a token of this kind travels: (place label, method, path, query, body, cookie)."""
    if kind == "ws_ticket":  # realtime/service.py: secrets.token_urlsafe(32)
        return [("GET /ws ticket", "GET", "/ws", {"ticket": value}, None, None),
                ("GET /ws/game ticket", "GET", "/ws/game", {"ticket": value, "room_id": "17"}, None, None)]
    if kind == "reset_token":  # auth/service.py: secrets.token_urlsafe(48), in the email link
        return [("POST /api/auth/reset-password token", "POST", "/api/auth/reset-password", {},
                 {"token": value, "new_password": pm_password()}, None),
                ("GET /reset-password (page) token", "GET", "/reset-password", {"token": value}, None, None)]
    if kind == "verify_jwt":  # email_verify JWT, 24 hours, with ver, in the email link
        return [("GET /api/auth/verify token", "GET", "/api/auth/verify", {"token": value}, None, None),
                ("GET /verify-email (page) token", "GET", "/verify-email", {"token": value}, None, None)]
    if kind == "refresh_jwt":  # refresh JWT, 30 days, no ver
        return [("POST /api/auth/refresh refresh_token", "POST", "/api/auth/refresh", {},
                 {"refresh_token": value}, None),
                ("POST /api/auth/logout refresh_token", "POST", "/api/auth/logout", {},
                 {"refresh_token": value}, None)]
    if kind == "oauth":  # state: secrets.token_urlsafe(32), also in a cookie; code: from 42
        state, code = value
        return [("GET /api/auth/oauth/42/callback code+state+cookie", "GET",
                 "/api/auth/oauth/42/callback", {"code": code, "state": state}, None,
                 "oauth42_state=" + state)]
    raise ValueError(kind)


def new_token(kind):
    if kind == "ws_ticket":
        return secrets.token_urlsafe(32)
    if kind == "reset_token":
        return secrets.token_urlsafe(48)
    if kind == "verify_jwt":
        return fake_jwt("email_verify", timedelta(hours=24))
    if kind == "refresh_jwt":
        return fake_jwt("refresh", timedelta(days=30), ver=False)
    if kind == "oauth":
        # 42's code: 64 lowercase hex characters (Doorkeeper's default, as seen in 42 sign-ins).
        return (secrets.token_urlsafe(32), secrets.token_hex(32))
    raise ValueError(kind)


TOKEN_KINDS = ["ws_ticket", "reset_token", "verify_jwt", "refresh_jwt", "oauth"]


# ---------------------------------------------------------------- HTTP, one keep-alive connection per thread
local = threading.local()
counter_lock = threading.Lock()
counter = [0]


def connection(fresh=False):
    if fresh or getattr(local, "conn", None) is None:
        local.conn = http.client.HTTPSConnection("localhost", PORT, context=CTX, timeout=30)
    return local.conn


def send(method, path, query=None, body=None, cookie=None, auth=None):
    """One request with a unique marker; returns (marker, status, is WAF block)."""
    with counter_lock:
        counter[0] += 1
        marker = "%s-%d" % (RUN, counter[0])
    # query: a dict, or a list of (name, value) pairs when a name repeats
    params = list(query.items()) if isinstance(query, dict) else list(query or [])
    params.append(("waf_sweep", marker))
    # As URLSearchParams encodes it (the frontend's way): space as "+", the rest as %XX.
    url = path + "?" + "&".join("%s=%s" % (urllib.parse.quote_plus(k, safe="*"),
                                           urllib.parse.quote_plus(str(v), safe="*"))
                                for k, v in params)
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en",
               "Host": "localhost" if PORT == 443 else "localhost:%d" % PORT}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")  # as JSON.stringify sends it
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = auth
    if cookie:
        headers["Cookie"] = cookie
    for attempt in (0, 1):
        try:
            conn = connection(fresh=attempt == 1)
            conn.request(method, url, body=data, headers=headers)
            res = conn.getresponse()
            payload = res.read()
            if res.getheader("Connection", "").lower() == "close":
                local.conn = None
            ctype = res.getheader("Content-Type", "")
            block = (res.status == 403 and ctype.startswith("text/html")
                     and b"<title>403 Forbidden</title>" in payload)
            return marker, res.status, block
        except (http.client.HTTPException, OSError):
            local.conn = None
            if attempt == 1:
                return marker, 0, False
    return marker, 0, False


def run_all(jobs):
    """jobs: list of (meta, send kwargs). Returns [(meta, marker, status, block)]."""
    def one(job):
        meta, kwargs = job
        return (meta,) + send(**kwargs)
    with ThreadPoolExecutor(THREADS) as pool:
        return list(pool.map(one, jobs))


# ---------------------------------------------------------------- audit lines: rules of each block
def audit_rules(since):
    time.sleep(1.5)  # the audit line is written when the transaction ends
    out = subprocess.run(["docker", "compose", "logs", "--no-log-prefix", "--since",
                          since.strftime("%Y-%m-%dT%H:%M:%SZ"), "proxy"], cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode("utf-8", "replace")
    found = {}
    for line in out.splitlines():
        if RUN not in line or '"transaction"' not in line:
            continue
        try:
            tx = json.loads(line)["transaction"]
        except ValueError:
            continue
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(tx.get("request", {}).get("uri", "")).query)
        marker = (query.get("waf_sweep") or [""])[0]
        rules = []
        for msg in tx.get("messages", []):
            d = msg.get("details", {})
            rid = d.get("ruleId", "?")
            if rid.startswith("949") or rid.startswith("980"):
                continue  # the score checks, not a match
            level = next((t.split("/")[1] for t in d.get("tags", []) if t.startswith("paranoia-level/")), "?")
            target = ""
            if " within " in d.get("data", ""):
                target = d["data"].split(" within ", 1)[1].split(": ", 1)[0]
            item = (rid, level, target)
            if item not in rules:
                rules.append(item)
        found[marker] = rules
    return found


def show_rules(rules):
    return ", ".join("%s (PL%s)%s" % (rid, level, " on " + target if target else "")
                     for rid, level, target in rules) or "no audit line found"


failures = []
report = {"run": RUN, "mode": MODE, "blocks": [], "summary": {}}


def text_sweep(sentences, title):
    since = datetime.now(timezone.utc) - timedelta(seconds=2)
    jobs = []
    for label, method, path, where, field, extra in FIELDS:
        for sentence in sentences:
            if where == "json":
                body = dict(extra)
                if "idempotency_key" in body:
                    body["idempotency_key"] = str(uuid.uuid4())
                body[field] = sentence
                kwargs = {"method": method, "path": path, "body": body, "auth": BEARER}
            else:
                query = dict(extra)
                query[field] = sentence
                kwargs = {"method": method, "path": path, "query": query, "auth": BEARER if path.startswith("/api/") else None}
            jobs.append(((label, field, sentence), kwargs))
    started = time.time()
    results = run_all(jobs)
    blocked = [r for r in results if r[3]]
    errors = [r for r in results if r[2] == 0]
    rules = audit_rules(since) if blocked else {}
    per_field = {}
    for (label, field, sentence), marker, status, block in results:
        key = "%s %s" % (label, field)
        sent, n = per_field.get(key, (0, 0))
        per_field[key] = (sent + 1, n + (1 if block else 0))
    print("%s: %d sentences x %d fields = %d requests in %.0fs" % (title, len(sentences), len(FIELDS), len(results), time.time() - started))
    for key, (sent, n) in per_field.items():
        print("  %-60s %4d sent, %3d WAF 403" % (key, sent, n))
    accepted = 0
    for (label, field, sentence), marker, status, block in blocked:
        found = rules.get(marker, [])
        pl1 = {rid for rid, level, _ in found if level == "1"}
        ok_fp = sentence in ACCEPTED and pl1 & set(ACCEPTED[sentence])
        report["blocks"].append({"sweep": title, "field": "%s %s" % (label, field), "text": sentence,
                                 "rules": found, "accepted": bool(ok_fp)})
        if ok_fp:
            accepted += 1
            print("  accepted  %s %s: %r -> WAF 403, %s" % (label, field, sentence, show_rules(found)))
        else:
            failures.append(1)
            print("  FAIL  %s %s: %r -> WAF 403, blocked by %s" % (label, field, sentence, show_rules(found)))
    for (label, field, sentence), marker, status, block in errors:
        failures.append(1)
        print("  FAIL  %s %s: %r -> no answer" % (label, field, sentence))
    report["summary"][title] = {"requests": len(results), "waf_403": len(blocked), "accepted": accepted}
    print("%s: %d WAF 403 (%d accepted false positives)" % (title, len(blocked), accepted))


def probe_sweep():
    jobs = []
    for label, method, path, where, field, extra in FIELDS:
        for probe in PROBES:
            if where == "json":
                body = dict(extra)
                if "idempotency_key" in body:
                    body["idempotency_key"] = str(uuid.uuid4())
                body[field] = probe
                kwargs = {"method": method, "path": path, "body": body, "auth": BEARER}
            else:
                query = dict(extra)
                query[field] = probe
                kwargs = {"method": method, "path": path, "query": query}
            jobs.append(((label, field, probe), kwargs))
    results = run_all(jobs)
    passed = [r for r in results if not r[3]]
    for (label, field, probe), marker, status, block in passed:
        failures.append(1)
        print("  FAIL  probe in %s %s: %r -> %s, expected the WAF's 403" % (label, field, probe, status))
    report["summary"]["probes"] = {"requests": len(results), "blocked": len(results) - len(passed)}
    print("probes: %d of %d attack probes in the free-text fields got the WAF's 403"
          % (len(results) - len(passed), len(results)))


def crs_regex():
    """One Python regex made of every @rx of the running proxy's CRS request rules at paranoia
    level 1 or 2 that reads ARGS or cookies; returns it and the ids Python cannot compile."""
    out = subprocess.run(["docker", "compose", "exec", "-T", "proxy", "sh", "-c",
                          "cat /opt/owasp-crs/rules/REQUEST-9*.conf"], cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode("utf-8", "replace")
    parts, skipped = [], []
    for m in re.finditer(r'^SecRule ([^ ]+) "@rx ((?:[^"\\]|\\.)*)" \\\n(.*?)(?=\n\n|\nSecRule|\Z)',
                         out, re.S | re.M):
        targets, rx, rest = m.groups()
        rid, level = re.search(r"id:(\d+)", rest), re.search(r"paranoia-level/(\d)", rest)
        if not rid or not level or int(level.group(1)) > 2:
            continue
        if not re.search(r"(?<![_A-Z])(?:ARGS|REQUEST_COOKIES)(?![_A-Z])", targets):
            continue
        rx = rx.replace('\\"', '"')
        flags = re.match(r"^\(\?([a-z]+)\)", rx)
        if flags:
            rx = "(?%s:%s)" % (flags.group(1), rx[flags.end():])
        try:
            re.compile(rx)
        except re.error:
            skipped.append(rid.group(1))
            continue
        parts.append("(?:%s)" % rx)
    return "|".join(parts), skipped


CRS_RX = None


def offline_chunk(args):
    kind, n = args
    found = []
    for _ in range(n):
        value = new_token(kind)
        if any(CRS_RX.search(v) for v in (value if isinstance(value, tuple) else (value,))):
            found.append(value)
    return found


def token_sweep(per_kind, prescreen, title):
    global CRS_RX
    pattern, skipped = crs_regex()
    CRS_RX = re.compile(pattern)
    print("%s: offline test with %d CRS regexes (PL1 and PL2, ARGS and cookies)%s" % (
        title, pattern.count("|(?:") + 1, "; not compilable in Python, covered by the sent values only: "
        + " ".join(skipped) if skipped else ""))
    for kind in TOKEN_KINDS:
        values = [new_token(kind) for _ in range(per_kind)]
        started = time.time()
        workers = os.cpu_count() or 2
        chunk = max(1, prescreen // (workers * 4))
        jobs_n = [(kind, min(chunk, prescreen - i)) for i in range(0, prescreen, chunk)]
        with multiprocessing.get_context("fork").Pool(workers) as pool:
            candidates = [v for part in pool.map(offline_chunk, jobs_n) for v in part]
        offline_seconds = time.time() - started
        since = datetime.now(timezone.utc) - timedelta(seconds=2)
        jobs = []
        for source, group in (("sent", values), ("offline match", candidates)):
            for value in group:
                for place, method, path, query, body, cookie in token_requests(kind, value):
                    auth = BEARER if path == "/api/auth/logout" else None
                    jobs.append(((source, place, value), {"method": method, "path": path, "query": query,
                                                          "body": body, "cookie": cookie, "auth": auth}))
        results = run_all(jobs)
        blocked = [r for r in results if r[3]]
        errors = [r for r in results if r[2] == 0]
        rules = audit_rules(since) if blocked else {}
        sent_blocks = sum(1 for r in blocked if r[0][0] == "sent")
        print("%s %s: %d values sent (%d requests, %d WAF 403); %d tested offline in %.0fs, %d matched a regex "
              "and were sent (%d WAF 403)" % (title, kind, per_kind, sum(1 for r in results if r[0][0] == "sent"),
                                             sent_blocks, prescreen, offline_seconds, len(candidates),
                                             len(blocked) - sent_blocks))
        by_rule = {}
        for (source, place, value), marker, status, block in blocked:
            found = rules.get(marker, [])
            failures.append(1)
            report["blocks"].append({"sweep": title, "kind": kind, "source": source, "place": place,
                                     "value": value, "rules": found})
            print("  FAIL  %s in %s -> WAF 403, blocked by %s" % (kind, place, show_rules(found)))
            for rid, level, target in found:
                by_rule.setdefault((rid, level, place, target), []).append(value)
                if rid in ("942100", "941100"):
                    print("  STOP  %s (libinjection, PL1) matched a %s: report the value pattern, lift nothing"
                          % (rid, kind))
        for (k, place, value), marker, status, block in errors:
            failures.append(1)
            print("  FAIL  %s in %s -> no answer" % (kind, place))
        for (rid, level, place, target), hits in sorted(by_rule.items()):
            print("    %s (PL%s) in %s on %s: %d values, e.g. %s" % (rid, level, place, target, len(hits), hits[0]))
        report["summary"]["%s %s" % (title, kind)] = {
            "sent": per_kind, "sent_waf_403": sent_blocks, "offline": prescreen,
            "offline_matches": len(candidates), "offline_waf_403": len(blocked) - sent_blocks}


# One value per token kind that a full sweep saw blocked before the token blocks 10050-10059
# (942100 on the 43- and 64-character ones, 942450 on the JWTs; docs/infra/waf.md "Token
# fields"). Each must now pass in every field of its kind.
TOKEN_SAMPLES = {
    "ws_ticket": "2-Cmqkh1f4bv9KiSZi41U2ImHag00twjV6z5C--n2-8",
    "reset_token": "8--XD2p58HUlt3BHLyp310djS2BkuZTm4cOVvkz7Cho3B03U5lO-YnDTRCA8s_2j",
    "verify_jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIzNjkwIiwic2NvcGUiOiJlbWFpbF92ZXJp"
                  "ZnkiLCJqdGkiOiJiMWZhNWM0YjhlYjU0M2UwYjg3MTFiZGRiZjFmY2FhMyIsImlhdCI6MTc5NTU0NjU3NSwi"
                  "ZXhwIjoxNzk1NjMyOTc1LCJ2ZXIiOjR9.13_0bGNck3y7SdniY96T-dzoRqTXqg-0XAB640q804g",
    "refresh_jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIzMzQ2Iiwic2NvcGUiOiJyZWZyZXNoIiwi"
                   "anRpIjoiZWMyNmZhYTgwZjY0NGRmNWIzYzg0MTI2Y2QyM2ZiOWMiLCJpYXQiOjE3OTU1MTE1NjMsImV4cCI6"
                   "MTc5ODEwMzU2M30.0xCa8crkg6fiRkGDBleGM1r6EhZmHONc0gc7_KMoVFM",
    "oauth": "1--Isx2uWSRO-4KOE7cFlMy_gfg4TpDym03a7JZdlps",  # the state
}

# The ten token fields of before-crs.conf, 10050-10059: (label, kind, method, path, where, name).
TOKEN_FIELDS = [
    ("GET /ws ARGS:ticket", "ws_ticket", "GET", "/ws", "query", "ticket"),
    ("GET /ws/game ARGS:ticket", "ws_ticket", "GET", "/ws/game", "query", "ticket"),
    ("GET /api/auth/oauth/42/callback ARGS:state", "oauth", "GET", "/api/auth/oauth/42/callback", "query", "state"),
    ("GET /api/auth/oauth/42/callback REQUEST_COOKIES:oauth42_state", "oauth", "GET",
     "/api/auth/oauth/42/callback", "cookie", "oauth42_state"),
    ("POST /api/auth/reset-password ARGS:json.token", "reset_token", "POST", "/api/auth/reset-password", "json", "token"),
    ("GET /reset-password (page) ARGS:token", "reset_token", "GET", "/reset-password", "query", "token"),
    ("GET /api/auth/verify ARGS:token", "verify_jwt", "GET", "/api/auth/verify", "query", "token"),
    ("GET /verify-email (page) ARGS:token", "verify_jwt", "GET", "/verify-email", "query", "token"),
    ("POST /api/auth/refresh ARGS:json.refresh_token", "refresh_jwt", "POST", "/api/auth/refresh", "json", "refresh_token"),
    ("POST /api/auth/logout ARGS:json.refresh_token", "refresh_jwt", "POST", "/api/auth/logout", "json", "refresh_token"),
]


def token_field_kwargs(field, value, second=None):
    """The real request of a token field with `value` in that field and valid values in the
    others; `second` adds a second value under the same name (query fields)."""
    label, kind, method, path, where, name = field
    query, body, cookie = {}, None, None
    if path == "/ws/game":
        query["room_id"] = "17"
    if kind == "oauth":
        state = secrets.token_urlsafe(32)
        query.update({"code": secrets.token_hex(32), "state": state})
        cookie = "oauth42_state=" + state
    if where == "query":
        query[name] = value
        if second is not None:
            query = list(query.items()) + [(name, second)]
    elif where == "json":
        body = {name: value}
        if kind == "reset_token":
            body["new_password"] = pm_password()
    else:
        cookie = "%s=%s" % (name, value)
    return {"method": method, "path": path, "query": query, "body": body, "cookie": cookie,
            "auth": BEARER if path == "/api/auth/logout" else None}


def fresh_value(kind):
    value = new_token(kind)
    return value[0] if kind == "oauth" else value


def token_samples():
    """The once-blocked sample and a fresh value of its kind in each token field: all must pass."""
    since = datetime.now(timezone.utc) - timedelta(seconds=2)
    jobs = []
    for field in TOKEN_FIELDS:
        for value in (TOKEN_SAMPLES[field[1]], fresh_value(field[1])):
            jobs.append(((field[0], value), token_field_kwargs(field, value)))
    results = run_all(jobs)
    blocked = [r for r in results if r[3]]
    rules = audit_rules(since) if blocked else {}
    for (label, value), marker, status, block in blocked:
        failures.append(1)
        print("  FAIL  token %s in %s -> WAF 403, blocked by %s" % (value, label, show_rules(rules.get(marker, []))))
    report["summary"]["token samples"] = {"requests": len(results), "waf_403": len(blocked)}
    print("tokens: %d requests (a once-blocked value and a fresh one in each of the %d token fields), %d WAF 403"
          % (len(results), len(TOKEN_FIELDS), len(blocked)))


def token_probe_sweep():
    """In each token field: two attacks, the once-blocked sample with one character turned
    into a space and into a quote (off the server's format, so every CRS rule applies again
    and 942100 or 942450 blocks it), and in the query fields the sample followed by a second
    value under the same name. Each must get the WAF's 403."""
    jobs = []
    for field in TOKEN_FIELDS:
        sample = TOKEN_SAMPLES[field[1]]
        probes = [("attack", "' OR 1=1 --"), ("attack", "<script>alert(1)</script>"),
                  ("off format", sample[:30] + " " + sample[31:]), ("off format", sample[:30] + "'" + sample[31:])]
        for what, value in probes:
            jobs.append(((field[0], what, value), token_field_kwargs(field, value)))
        if field[4] == "query":
            jobs.append(((field[0], "second value", sample + " & ' OR 1=1 --"),
                         token_field_kwargs(field, sample, second="' OR 1=1 --")))
    results = run_all(jobs)
    passed = [r for r in results if not r[3]]
    for (label, what, value), marker, status, block in passed:
        failures.append(1)
        print("  FAIL  %s probe in %s: %r -> %s, expected the WAF's 403" % (what, label, value, status))
    report["summary"]["token probes"] = {"requests": len(results), "blocked": len(results) - len(passed)}
    print("token probes: %d of %d probes in the %d token fields got the WAF's 403"
          % (len(results) - len(passed), len(results), len(TOKEN_FIELDS)))


if MODE == "ci":
    text_sweep(corpus(subset=True), "corpus subset")
    token_samples()
    token_probe_sweep()
    probe_sweep()
if MODE in ("corpus", "all"):
    text_sweep(corpus(subset=False), "corpus")
    probe_sweep()
if MODE in ("tokens", "all"):
    token_sweep(PER_KIND, PRESCREEN, "tokens")
    token_samples()
    token_probe_sweep()

if REPORT:
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
if failures:
    print("waf-sweep: FAILED (%d)" % len(failures))
    sys.exit(1)
print("waf-sweep: all checks passed")
PY
