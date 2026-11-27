#!/usr/bin/env bash
# WAF check (INF-11), from the host, over HTTPS through the proxy:
# 1. the running proxy has the engine On, paranoia level 2 (blocking and detection), the
#    anomaly thresholds 5 inbound and 4 outbound, audit log parts AHZ, and the two exclusion
#    files of infra/proxy/modsecurity mounted; read from the container (env, the generated
#    config and the mounted files) and shown by behaviour (a probe only a PL2 rule catches
#    is blocked; audit lines carry no request headers or bodies), and the pages send
#    Referrer-Policy: strict-origin;
# 2. attack probes (SQL injection and XSS in a query string and in a JSON body, path
#    traversal, a scanner User-Agent, a PL2-only probe) each get the WAF's 403 and leave an
#    audit line in `docker compose logs proxy`, found by its unique URI;
# 3. a corpus of normal traffic never gets the WAF's 403: two users signed up and verified
#    as mail-check does, with password-manager passwords (symbols), login and refresh, a
#    password change and a reset through the email link, profile text with quotes, "--", a URL, emoji,
#    Arabic and Russian, a company and a job, a conversation (send, edit, delete), avatar
#    and intro video uploads (presigned PUT) with their confirm, a game round (queue, start,
#    room, chat history, both WebSocket handshakes, a vote refused with the app's 409, leave),
#    the Grafana dashboards as the browser loads them and its snapshot refusal, then both
#    accounts deleted; a job search with the jobs page's full URL as Referer passes too.
# 4. no audit line of the run holds a secret the run sent or got: passwords, access and
#    refresh tokens, email link tokens, WebSocket tickets, presigned URL signatures, the
#    Grafana admin password (searched for, never printed).
# A WAF 403 is nginx's HTML page (<title>403 Forbidden</title>); the app's errors are JSON
# ({"error": ...}), Grafana's too. Every request is told apart that way.
# Prints "waf-check: N probes blocked, M normal requests passed"; exits 1 on any miss, with
# the request and the rule ids from its audit line.
# Then runs `infra/proxy/waf-sweep.sh ci`: the "* " sentences of waf-corpus.txt in every
# free-text field, a value per token kind in its place, and 3 attack probes in every
# free-text field. WAF_SWEEP=1 adds the full sweep (`waf-sweep.sh all`, about 3 minutes,
# not in CI). Exits 1 if any part failed.
# Needs the stack up (`make`). Run it with `make waf-check`. Signs up 2 users: the API allows
# 5 sign-ups a minute per address, so wait a minute between two runs (mail-check signs up one).
# Needs Python 3.9+ (standard library only) and docker. Works with bash 3.2 (macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

for service in proxy api mailpit grafana; do
    if [ -z "$(docker compose ps -q "$service")" ]; then
        echo "waf-check: the stack is not running; start it with make" >&2
        exit 1
    fi
done

https_port="$(docker compose port proxy 8443)"
https_port="${https_port##*:}"
if [ "$https_port" = 443 ]; then base=https://localhost; else base="https://localhost:$https_port"; fi

rc=0
python3 -I - "$ROOT" "$base" <<'PY' || rc=1
import base64
import glob
import hashlib
import json
import os
import random
import re
import socket
import ssl
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from datetime import datetime, timedelta, timezone

ROOT, BASE = sys.argv[1], sys.argv[2]
CA = os.path.join(ROOT, "infra/proxy/certs/server.crt")
HOST = urllib.parse.urlsplit(BASE).hostname
PORT = urllib.parse.urlsplit(BASE).port or 443
RUN = uuid.uuid4().hex[:10]
STARTED = datetime.now(timezone.utc) - timedelta(seconds=2)
CTX = ssl.create_default_context(cafile=CA)
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
# What the proxy must run with (infra/proxy/proxy.env).
EXPECTED_ENV = {"MODSEC_RULE_ENGINE": "On", "BLOCKING_PARANOIA": "2", "DETECTION_PARANOIA": "2",
                "ANOMALY_INBOUND": "5", "ANOMALY_OUTBOUND": "4", "MODSEC_AUDIT_LOG_PARTS": "AHZ"}
CRS_RULES = "/opt/owasp-crs/rules"
MOUNTS = {"infra/proxy/modsecurity/before-crs.conf": CRS_RULES + "/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf",
          "infra/proxy/modsecurity/after-crs.conf": CRS_RULES + "/RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf"}

failures = []
probes_blocked = 0
normal_passed = 0
sent = []  # (kind, label, method, uri path+query) of every request, for the audit lookup
# Every secret the run sends or receives (passwords, tokens, tickets, URL signatures), with
# what it is: no audit line may contain one (checked at the end, never printed).
secrets = []
counter = [0]


def ok(text):
    print("  ok    " + text)


def fail(text):
    print("  FAIL  " + text)
    failures.append(text)


def compose(*args):
    out = subprocess.run(["docker", "compose"] + list(args), cwd=ROOT, check=False,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return out.returncode, out.stdout.decode("utf-8", "replace")


def mark(url):
    """The URL with ?waf_check=<run>-<n>: its audit line, if any, is found by this URI."""
    counter[0] += 1
    sep = "&" if "?" in url else "?"
    return "%s%swaf_check=%s-%d" % (url, sep, RUN, counter[0])


def http(method, url, body=None, headers=None, ctype=None, auth=None, ua=BROWSER_UA):
    """One request. body: dict (sent as JSON) or bytes (sent with ctype). Returns
    (status, content type, body bytes); status 0 when the connection failed."""
    full = url if url.startswith("https://") else BASE + url
    data = None
    hdrs = {"User-Agent": ua, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en"}
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data, hdrs["Content-Type"] = bytes(body), ctype
        else:
            data, hdrs["Content-Type"] = json.dumps(body).encode(), "application/json"
    if auth:
        hdrs["Authorization"] = auth
    hdrs.update(headers or {})
    req = urllib.request.Request(full, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as res:
            return res.status, res.headers.get("Content-Type", ""), res.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get("Content-Type", ""), err.read()
    except Exception as err:  # connection cut (an outbound block), timeout, TLS error
        return 0, "", repr(err).encode()


def is_waf_block(status, ctype, body):
    return status == 403 and ctype.startswith("text/html") and b"<title>403 Forbidden</title>" in body


def path_of(url):
    parts = urllib.parse.urlsplit(url if url.startswith("https://") else BASE + url)
    return parts.path + ("?" + parts.query if parts.query else "")


def normal(label, method, url, expected, body=None, json_error=False, **kw):
    """A request of the corpus. expected: the statuses the app answers it with. json_error:
    a JSON error from the app (4xx with a JSON body) is accepted too. Returns the parsed
    JSON answer, or None."""
    global normal_passed
    status, ctype, data = http(method, url, body, **kw)
    sent.append(("normal", label, method, path_of(url)))
    answer = None
    if "json" in ctype:
        try:
            answer = json.loads(data or b"null")
        except ValueError:
            answer = None
    if is_waf_block(status, ctype, data):
        fail("%s: %s %s -> WAF 403" % (label, method, urllib.parse.urlsplit(path_of(url)).path))
        failures[-1] = (label, method, path_of(url))
        return None
    if status in expected or (json_error and 400 <= status < 500 and "json" in ctype):
        normal_passed += 1
        ok("%s: %s %s -> %s" % (label, method, urllib.parse.urlsplit(path_of(url)).path, status))
        return answer
    fail("%s: %s %s -> %s %s, expected %s" % (label, method, urllib.parse.urlsplit(path_of(url)).path,
                                              status, data[:120].decode("utf-8", "replace"), expected))
    return answer


def probe(label, method, url, body=None, ua=BROWSER_UA):
    """An attack probe: it must get the WAF's 403."""
    global probes_blocked
    status, ctype, data = http(method, url, body, ua=ua)
    sent.append(("probe", label, method, path_of(url)))
    if is_waf_block(status, ctype, data):
        probes_blocked += 1
        ok("probe %s: WAF 403" % label)
    else:
        fail("probe %s: %s %s, expected the WAF's 403" % (label, status, data[:80].decode("utf-8", "replace")))


# ---------------------------------------------------------------------------- 1. config
print("waf-check: %s (run %s)" % (BASE, RUN))
print("1. Proxy configuration:")
names = list(EXPECTED_ENV)
code, out = compose("exec", "-T", "proxy", "printenv", *names)
values = out.splitlines()
for name, value in zip(names, values + [""] * len(names)):
    if value == EXPECTED_ENV[name]:
        ok("%s=%s" % (name, value))
    else:
        fail("%s=%s, expected %s" % (name, value, EXPECTED_ENV[name]))
code, out = compose("exec", "-T", "proxy", "sh", "-c",
                    "grep -hE '^[[:space:]]*Sec(RuleEngine|AuditLogParts) ' /etc/modsecurity.d/modsecurity.conf; "
                    "grep -hoE 'tx\\.(blocking_paranoia_level|detection_paranoia_level|"
                    "inbound_anomaly_score_threshold|outbound_anomaly_score_threshold)=[0-9]+' "
                    "/etc/modsecurity.d/owasp-crs/crs-setup.conf")
live = " ".join(out.split())
for want in ("SecRuleEngine On", "SecAuditLogParts AHZ", "tx.blocking_paranoia_level=2",
             "tx.detection_paranoia_level=2", "tx.inbound_anomaly_score_threshold=5",
             "tx.outbound_anomaly_score_threshold=4"):
    if want in live:
        ok("live config: %s" % want)
    else:
        fail("live config: %s missing" % want)
for repo_file, mounted in sorted(MOUNTS.items()):
    with open(os.path.join(ROOT, repo_file), "rb") as fh:
        want = hashlib.sha256(fh.read()).hexdigest()
    code, out = compose("exec", "-T", "proxy", "sha256sum", mounted)
    if out.split()[:1] == [want]:
        ok("%s is mounted as %s" % (repo_file, os.path.basename(mounted)))
    else:
        fail("%s is not what the proxy loads at %s" % (repo_file, mounted))

# The pages send Referrer-Policy: strict-origin (default.conf.template, location /), so the
# browser sends only the origin as Referer, never a page's query (a search, a reset token).
try:
    with urllib.request.urlopen(urllib.request.Request(BASE + "/", method="GET", headers={
            "User-Agent": BROWSER_UA}), context=CTX, timeout=30) as res:
        policy = res.headers.get("Referrer-Policy")
except Exception as err:  # noqa: BLE001 - reported as a failure below
    policy = "no answer (%r)" % err
if policy == "strict-origin":
    ok("GET / sends Referrer-Policy: strict-origin")
else:
    fail("GET / sends Referrer-Policy: %s, expected strict-origin" % policy)

# ---------------------------------------------------------------------------- 2. probes
print("2. Attack probes (each must get the WAF's 403):")
probe("SQL injection in a query string", "GET",
      mark("/api/jobs/open?keyword=" + urllib.parse.quote("1' UNION SELECT password FROM users--")))
probe("SQL injection in a JSON body", "POST", mark("/api/conversations/1/messages"),
      {"content": "x' OR '1'='1' UNION SELECT email, password_hash FROM users --"})
probe("XSS in a query string", "GET",
      mark("/api/jobs/open?keyword=" + urllib.parse.quote("<script>alert(document.cookie)</script>")))
probe("XSS in a JSON body", "PATCH", mark("/api/users/me"),
      {"bio": "<img src=x onerror=alert(document.domain)>"})
probe("path traversal", "GET", mark("/api/media/feed?cursor=" + urllib.parse.quote("../../../../etc/passwd")))
probe("scanner User-Agent", "GET", mark("/api/health"), ua="sqlmap/1.8.11#stable (https://sqlmap.org)")
# 941380 (AngularJS template injection) is a paranoia level 2 rule and the only one that
# matches {{x}}: at PL1 this probe would pass.
PL2_PROBE = mark("/api/jobs/open?keyword=" + urllib.parse.quote("{{x}}"))
probe("PL2 only (template braces)", "GET", PL2_PROBE)

# ---------------------------------------------------------------------------- 3. corpus
print("3. Normal traffic (must never get the WAF's 403):")
MAIL = "/mail/api/v1"


def new_password():
    """A password as a password manager makes one: random, with symbols. The fixed part alone
    got the WAF's 403 at PL2 before the password exclusions (932240, 942131); a password
    is never inspected now (before-crs.conf, "passwords")."""
    password = "Zq8#vL2!pR$-wN" + 'a"b<c>d' + base64.urlsafe_b64encode(os.urandom(9)).decode()
    secrets.append(("a password", password))
    return password


def mail_token(label, email, page):
    """The token of the newest email link to <page>?token=... sent to email, from Mailpit;
    the email is deleted afterwards."""
    search = MAIL + "/search?" + urllib.parse.urlencode({"query": "to:" + email})
    message_id = None
    for _ in range(30):  # the API sends the email in the background
        status, ctype, data = http("GET", search)
        if status == 200 and json.loads(data).get("messages"):
            found = normal("Mailpit search " + label, "GET", mark(search), (200,)) or {}
            message_id = (found.get("messages") or [{}])[0].get("ID")
            break
        time.sleep(1)
    if message_id is None:
        fail("%s: no email to %s in Mailpit after 30 s (make logs s=api)" % (label, email))
        return None
    message = normal("Mailpit message " + label, "GET", mark(MAIL + "/message/" + message_id), (200,)) or {}
    link = re.search(page + r"\?token=([A-Za-z0-9._-]+)", (message.get("HTML") or "") + (message.get("Text") or ""))
    normal("Mailpit delete " + label, "DELETE", mark(MAIL + "/messages"), (200,), {"IDs": [message_id]})
    if not link:
        fail("%s: no %s link in the email" % (label, page))
        return None
    secrets.append(("an email link token", link.group(1)))
    return link.group(1)


def log_in(user, label, password):
    """Log in and keep the new tokens in user; None when it failed."""
    tokens = normal(label, "POST", mark("/api/auth/login"), (200,), {"email": user["email"], "password": password})
    if not tokens:
        return None
    secrets.append(("an access token", tokens["access_token"]))
    secrets.append(("a refresh token", tokens["refresh_token"]))
    user.update(tokens=tokens, auth="Bearer " + tokens["access_token"], password=password)
    return user


def sign_up(tag):
    """Register, verify through the email's link (read from Mailpit), log in: as mail-check."""
    user = {"email": "waf-check-%s-%s@example.com" % (RUN, tag)}
    password = new_password()
    normal("sign up " + tag, "POST", mark("/api/auth/register"), (202,), {"email": user["email"], "password": password})
    token = mail_token("sign up " + tag, user["email"], "verify-email")
    if not token:
        return None
    normal("verify " + tag, "GET", mark("/api/auth/verify?token=" + token), (200,))
    if not log_in(user, "login " + tag, password):
        return None
    me = normal("profile " + tag, "GET", mark("/api/users/me"), (200,), auth=user["auth"]) or {}
    user["id"] = me.get("id")
    return user


def tiny_png():
    """A real 16x16 PNG (the avatar confirm opens it with Pillow)."""
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    rows = b"".join(b"\x00" + bytes((40 + y * 10, 120, 200)) * 16 for y in range(16))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def fake_mp4(size):
    """An MP4 file type box and then fixed pseudo-random bytes: binary like a real video,
    and the same bytes on every run, so a rule hit on it is reproducible."""
    head = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
    return head + random.Random(11).randbytes(size - len(head))


def ws_handshake(label, path):
    """The WebSocket upgrade, the only part of a socket the WAF sees. Returns the first frame's
    text (or "" when none came within 2 s); None when the upgrade failed."""
    global normal_passed
    key = base64.b64encode(os.urandom(16)).decode()
    sent.append(("normal", label, "GET", path))
    raw = socket.create_connection((HOST, PORT), timeout=10)
    sock = CTX.wrap_socket(raw, server_hostname=HOST)
    try:
        sock.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\nUpgrade: websocket\r\n"
                      "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
                      "Origin: %s\r\n\r\n" % (path, urllib.parse.urlsplit(BASE).netloc, BROWSER_UA,
                                              key, BASE)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                break
            head += chunk
        status_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
                                               .encode()).digest()).decode()
        if " 101 " not in status_line + " " or accept.encode() not in head:
            if b"<title>403 Forbidden</title>" in head:
                fail("%s: GET %s -> WAF 403" % (label, path.split("?")[0]))
                failures[-1] = (label, "GET", path)
            else:
                fail("%s: %s, expected 101 with a matching Sec-WebSocket-Accept" % (label, status_line))
            return None
        rest = head.split(b"\r\n\r\n", 1)[1]
        sock.settimeout(2)
        try:
            while len(rest) < 2:
                rest += sock.recv(4096)
            length = rest[1] & 0x7F
            start = 2
            if length == 126:
                while len(rest) < 4:
                    rest += sock.recv(4096)
                length, start = struct.unpack(">H", rest[2:4])[0], 4
            while len(rest) < start + length:
                rest += sock.recv(65536)
            opcode, payload = rest[0] & 0x0F, rest[start:start + length]
        except socket.timeout:
            opcode, payload = None, b""
        if opcode == 8:  # close: 1008 means the ticket was refused
            fail("%s: 101, then closed (%s)" % (label, payload[2:].decode("utf-8", "replace")))
            return None
        normal_passed += 1
        ok("%s: GET %s -> 101%s" % (label, path.split("?")[0], ", first frame " + payload[:40].decode(
            "utf-8", "replace") if payload else ""))
        return payload.decode("utf-8", "replace")
    finally:
        sock.close()


a = sign_up("a")
b = sign_up("b")
if not a or not b:
    fail("corpus: the two users could not be created; the rest of the corpus is skipped")
else:
    refreshed = normal("refresh a", "POST", mark("/api/auth/refresh"), (200,),
                       {"refresh_token": a["tokens"]["refresh_token"]})
    if refreshed:
        a["tokens"], a["auth"] = refreshed, "Bearer " + refreshed["access_token"]
        secrets.extend([("an access token", refreshed["access_token"]),
                        ("a refresh token", refreshed["refresh_token"])])

    # Realistic free text: an apostrophe, "--", words that are SQL keywords, a URL with a
    # query string, emoji, Arabic and Russian.
    normal("profile text a", "PATCH", mark("/api/users/me"), (200,), {
        "first_name": "Seán", "last_name": "O'Brien", "position": "Senior engineer -- backend",
        "bio": "Hi! Please select a job, then update your profile. Portfolio: "
               "https://example.com/portfolio?lang=en&tab=work 🙂🚀 مرحبا بكم، Привет, мир!"},
           auth=a["auth"])
    normal("profile text b", "PATCH", mark("/api/users/me"), (200,), {
        "first_name": "Мария", "last_name": "Аль-Хаддад", "position": "Product designer",
        "bio": "I'm looking for part-time work -- weekends only. "
               "Мой сайт: https://example.org/maria и телефон +971 50 123 4567. شكراً 👋"},
           auth=b["auth"])

    normal("company", "POST", mark("/api/companies"), (201,), {
        "name": "O'Brien & Sons Ltd.", "description": "We build things -- fast. Select a job, then "
        "update your profile; we'll call you back. Website: https://example.com/about مرحبا",
        "country": "United Arab Emirates",
        "city": "Abu Dhabi", "district": "Al Reem Island"}, auth=a["auth"])
    normal("company edit", "PATCH", mark("/api/companies/me"), (200,), {
        "name": "O'Brien & Sons -- Abu Dhabi", "country": "United Arab Emirates",
        "city": "Abu Dhabi", "district": "Al Reem Island, 2 or 3 min from the metro"}, auth=a["auth"])
    job = normal("job create", "POST", mark("/api/jobs"), (201,), {
        "title": "Backend developer (Python, SQL)", "description":
        "Experience with SQL and PostgreSQL; select a job, then update your profile -- we reply "
        "within 2 days. Details: https://example.com/jobs?id=42&ref=board 🙂 مرحبا Привет",
        "latitude": 24.4539, "longitude": 54.3773, "location": "Abu Dhabi, Al Reem Island",
        "status": "open", "salary_amount": "12000.00", "salary_type": "monthly",
        "salary_currency": "AED", "schedule": "full_time", "urgency": "normal"}, auth=a["auth"]) or {}
    normal("my jobs", "GET", mark("/api/jobs/mine"), (200,), auth=a["auth"])
    if job.get("id"):
        normal("job", "GET", mark("/api/jobs/%d" % job["id"]), (200,), auth=b["auth"])
        normal("job edit", "PATCH", mark("/api/jobs/%d" % job["id"]), (200,), {
            "urgency": "urgent", "title": "Senior engineer -- backend (2 or 3 hires)",
            "description": "We hire 2 or 3 people each year -- O'Brien's team. Yes, I'm in!"},
            auth=a["auth"])
    # The search page's request (frontend/src/features/jobs/api.ts).
    normal("job search", "GET", mark("/api/jobs/open?" + urllib.parse.urlencode({
        "keyword": "backend developer -- O'Brien", "salary_min": 1000, "lat": 24.45, "lng": 54.38})),
        (200,), auth=b["auth"])
    # The same search with the Referer a browser without our Referrer-Policy sends: the jobs
    # page's own URL with its query. 932206 blocked it until INF-11 (#94 review); 10040 lifts
    # that rule for the API, whose code never reads the Referer.
    normal("job search with a full-URL Referer", "GET",
           mark("/api/jobs/open?keyword=backend+developer"), (200,), auth=b["auth"],
           headers={"Referer": BASE + "/jobs?keyword=backend+developer"})

    conv = normal("conversation", "POST", mark("/api/conversations"), (201,),
                  {"type": "direct", "peer_user_id": b["id"], "job_id": job.get("id")}, auth=a["auth"]) or {}
    if conv.get("id"):
        cid = conv["id"]
        sent_a = normal("message a", "POST", mark("/api/conversations/%d/messages" % cid), (200, 201), {
            "content": "Hi Мария! Please select a job, then update your profile -- thanks 🙂",
            "idempotency_key": uuid.uuid4().hex}, auth=a["auth"]) or {}
        normal("message b", "POST", mark("/api/conversations/%d/messages" % cid), (200, 201), {
            "content": "Sure, Mr O'Brien! مرحبا. See https://example.org/a?b=c&d=e -- I'll update it today. "
                       "Мой сайт: https://example.org/maria и телефон +971 50 123 4567.",
            "idempotency_key": uuid.uuid4().hex}, auth=b["auth"])
        normal("history", "GET", mark("/api/conversations/%d/messages" % cid), (200,), auth=b["auth"])
        items = sent_a.get("items") or []
        if items:
            mid = items[-1]["id"]
            normal("message edit", "PATCH", mark("/api/conversations/%d/messages/%d" % (cid, mid)), (200,),
                   {"content": "Hi Мария! Please select a job, then update your profile -- edited 🙂"},
                   auth=a["auth"])
            normal("read", "POST", mark("/api/conversations/%d/read" % cid), (204,),
                   {"last_message_id": mid}, auth=b["auth"])
            normal("message delete", "DELETE", mark("/api/conversations/%d/messages/%d" % (cid, mid)),
                   (204,), auth=a["auth"])
        normal("conversations", "GET", mark("/api/conversations"), (200,), auth=b["auth"])
        normal("unread", "GET", mark("/api/conversations/unread"), (200,), auth=b["auth"])

    up = normal("avatar upload-url", "POST", mark("/api/media/avatar/upload-url?ext=png"), (200,),
                auth=a["auth"]) or {}
    if up.get("put_url"):
        secrets.append(("a presigned URL signature",
                        urllib.parse.parse_qs(urllib.parse.urlsplit(up["put_url"]).query)["X-Amz-Signature"][0]))
        # The presigned URL is unique; a marker would break its signature.
        normal("avatar PUT (image/png)", "PUT", up["put_url"], (200,), tiny_png(), ctype="image/png")
        normal("avatar confirm", "POST", mark("/api/media/avatar/confirm"), (204,),
               {"object_key": up["object_key"]}, auth=a["auth"])
    video = fake_mp4(300 * 1024)
    up = normal("video upload-url", "POST", mark("/api/media/intro-video/upload-url"), (200,),
                {"content_type": "video/mp4", "ext": "mp4"}, auth=b["auth"]) or {}
    if up.get("put_url"):
        secrets.append(("a presigned URL signature",
                        urllib.parse.parse_qs(urllib.parse.urlsplit(up["put_url"]).query)["X-Amz-Signature"][0]))
        normal("video PUT (video/mp4, 300 kB)", "PUT", up["put_url"], (200,), video, ctype="video/mp4")
        normal("video confirm", "POST", mark("/api/media/intro-video/confirm"), (201,),
               {"object_key": up["object_key"], "duration_sec": 12, "size_bytes": len(video),
                "content_type": "video/mp4"}, auth=b["auth"])
        normal("my videos", "GET", mark("/api/media/intro-video/mine"), (200,), auth=b["auth"])

    room_a = normal("game join a", "POST", mark("/api/game/queue/join"), (202,), auth=a["auth"]) or {}
    room_b = normal("game join b", "POST", mark("/api/game/queue/join"), (202,), auth=b["auth"]) or {}
    room = room_a.get("room_id")
    if room:
        # 200 once started; the app's 409 JSON when another room held b (start needs 2 to 4).
        normal("game start", "POST", mark("/api/game/rooms/%d/start" % room), (200,), json_error=True,
               auth=a["auth"])
        normal("game room", "GET", mark("/api/game/rooms/%d" % room), (200,), auth=a["auth"])
        normal("game chat history", "GET", mark("/api/game/rooms/%d/messages" % room), (200,), auth=a["auth"])
        ticket = normal("ws ticket a", "POST", mark("/api/ws/ticket"), (200,), auth=a["auth"]) or {}
        if ticket.get("ticket"):
            secrets.append(("a WebSocket ticket", ticket["ticket"]))
            first = ws_handshake("room socket /ws/game", mark("/ws/game?" + urllib.parse.urlencode(
                {"ticket": ticket["ticket"], "room_id": room})))
            if first is not None and "game_snapshot" not in first:
                fail("room socket /ws/game: first frame is not a game_snapshot")
        ticket = normal("ws ticket b", "POST", mark("/api/ws/ticket"), (200,), auth=b["auth"]) or {}
        if ticket.get("ticket"):
            secrets.append(("a WebSocket ticket", ticket["ticket"]))
            ws_handshake("socket /ws", mark("/ws?" + urllib.parse.urlencode({"ticket": ticket["ticket"]})))
        # During the discussion the app refuses votes with its own 409 JSON.
        normal("game vote", "POST", mark("/api/game/rooms/%d/votes" % room), (200, 409),
               {"target_participant_id": 2, "guess": "bot"}, auth=a["auth"])
        normal("game results", "GET", mark("/api/game/rooms/%d/results" % room), (200, 409), auth=a["auth"])
    normal("game leave a", "DELETE", mark("/api/game/queue/leave"), (204,), auth=a["auth"])
    normal("game leave b", "DELETE", mark("/api/game/queue/leave"), (204,), auth=b["auth"])

    # The other two password fields: a changes the password, b resets it through the email
    # link; each logs in again with the new one (both revoke every token).
    password, before = new_password(), len(failures)
    normal("change password a", "POST", mark("/api/auth/change-password"), (204,),
           {"current_password": a["password"], "new_password": password}, auth=a["auth"])
    if len(failures) == before:
        log_in(a, "login a with the changed password", password)
    normal("forgot password b", "POST", mark("/api/auth/forgot-password"), (202,), {"email": b["email"]})
    token = mail_token("reset b", b["email"], "reset-password")
    if token:
        password, before = new_password(), len(failures)
        normal("reset password b", "POST", mark("/api/auth/reset-password"), (204,),
               {"token": token, "new_password": password})
        if len(failures) == before:
            log_in(b, "login b with the reset password", password)

    normal("logout b", "POST", mark("/api/auth/logout"), (204,),
           {"refresh_token": b["tokens"]["refresh_token"]}, auth=b["auth"])
    normal("delete account a", "DELETE", mark("/api/users/me"), (204,), auth=a["auth"])
    normal("delete account b", "DELETE", mark("/api/users/me"), (204,), auth=b["auth"])

# Grafana as the browser uses it, with the admin password read from the running container
# (kept in memory, never printed): the file vault-agent-infra renders into the grafana
# container's tmpfs (INF-13). This covers the Grafana exclusions of before-crs.conf.
code, out = compose("exec", "-T", "grafana", "cat", "/run/vault/admin-password")
password = out.strip() if code == 0 else ""
if password:
    secrets.append(("the Grafana admin password", password))
if not password:
    fail("Grafana: could not read the admin password from the container")
else:
    admin = "Basic " + base64.b64encode(("admin:" + password).encode()).decode()
    del password
    normal("Grafana login page", "GET", mark("/grafana/login"), (200,))
    dashboards = []
    for path in sorted(glob.glob(os.path.join(ROOT, "infra/grafana/dashboards/*.json"))):
        with open(path) as fh:
            dashboards.append(json.load(fh))
    now = int(time.time())
    for dash in dashboards:
        normal("Grafana dashboard " + dash.get("title", "?"), "GET",
               mark("/grafana/api/dashboards/uid/" + dash["uid"]), (200,), auth=admin)
        for var in dash.get("templating", {}).get("list", []):
            found = re.match(r"label_values\(([^,]+),\s*(\w+)\)", var.get("definition", ""))
            if found:
                normal("Grafana variable " + var["name"], "GET", mark(
                    "/grafana/api/datasources/uid/prometheus/resources/api/v1/label/%s/values?%s" % (
                        found.group(2), urllib.parse.urlencode({"match[]": found.group(1),
                                                                "start": now - 900, "end": now}))),
                    (200,), auth=admin)
        for panel in dash.get("panels", []):
            queries = []
            for target in panel.get("targets", []):
                queries.append({
                    "refId": target["refId"], "expr": re.sub(r"\$\{?project\}?", "server", target["expr"]),
                    "legendFormat": target.get("legendFormat", ""), "range": True, "instant": False,
                    "exemplar": False, "interval": "", "utcOffsetSec": 14400,
                    "datasource": {"type": "prometheus", "uid": "prometheus"},
                    "requestId": "%s%s" % (panel.get("id"), target["refId"]), "intervalMs": 15000,
                    "maxDataPoints": 1200})
            if queries:
                normal("Grafana panel " + panel.get("title", "?"), "POST",
                       mark("/grafana/api/ds/query?ds_type=prometheus"), (200,),
                       {"queries": queries, "from": str((now - 900) * 1000), "to": str(now * 1000)},
                       auth=admin)
    if dashboards:
        # Snapshots are off in Grafana: it must be Grafana that refuses, with its own JSON 403.
        url = mark("/grafana/api/snapshots")
        status, ctype, data = http("POST", url, {"dashboard": dashboards[0], "name": "waf-check",
                                                 "expires": 60}, auth=admin)
        sent.append(("normal", "Grafana snapshot", "POST", path_of(url)))
        if status == 403 and b"Dashboard Snapshots are disabled" in data:
            normal_passed += 1
            ok("Grafana snapshot: POST /grafana/api/snapshots -> 403 from Grafana (snapshots disabled)")
        elif is_waf_block(status, ctype, data):
            fail("Grafana snapshot: POST /grafana/api/snapshots -> WAF 403")
            failures[-1] = ("Grafana snapshot", "POST", sent[-1][3])
        else:
            fail("Grafana snapshot: %s %s, expected Grafana's 403" % (status, data[:80]))

# ---------------------------------------------------------------------------- audit lines
time.sleep(1)  # the audit line is written when the transaction ends
code, out = compose("logs", "--no-log-prefix", "--since", STARTED.strftime("%Y-%m-%dT%H:%M:%SZ"), "proxy")
audit = {}
audit_lines = audit_bytes = 0
leaks = []
for line in out.splitlines():
    if '"transaction"' not in line:
        continue
    try:
        tx = json.loads(line)["transaction"]
    except ValueError:
        continue
    # Every audit line since the start, marked or not; JSON escapes " and \ in the line.
    for what, value in secrets:
        if value and (value in line or json.dumps(value)[1:-1] in line):
            leaks.append((what, tx.get("request", {}).get("method"), tx.get("request", {}).get("uri", "").split("?")[0]))
    uri = tx.get("request", {}).get("uri", "")
    if RUN not in uri and "/files/" not in uri:
        continue
    audit_lines += 1
    audit_bytes += len(line) + 1
    audit.setdefault((tx["request"].get("method"), uri), []).append(tx)


def rules_of(txs):
    seen = []
    for tx in txs:
        for msg in tx.get("messages", []):
            d = msg.get("details", {})
            target = ""
            if " within " in d.get("data", ""):
                target = " on " + d["data"].split(" within ", 1)[1].split(":", 1)[0]
            item = d.get("ruleId", "?") + target
            if item not in seen:
                seen.append(item)
    return seen


print("Audit lines:")
for kind, label, method, uri in sent:
    txs = audit.get((method, uri), [])
    if kind == "probe":
        if not txs:
            fail("probe %s: no audit line for %s %s" % (label, method, uri.split("?")[0]))
            continue
        rules = rules_of(txs)
        ok("probe %s: %s" % (label, " ".join(r.split(" on ")[0] for r in rules)))
        if any(k in txs[0]["request"] for k in ("headers", "body")) or "body" in txs[0].get("response", {}):
            fail("probe %s: the audit line holds headers or a body (parts other than AHZ)" % label)
        if uri == PL2_PROBE:
            pl2 = [m["details"]["ruleId"] for m in txs[0]["messages"]
                   if "paranoia-level/2" in m["details"].get("tags", [])]
            pl1 = [m["details"]["ruleId"] for m in txs[0]["messages"]
                   if "paranoia-level/1" in m["details"].get("tags", [])]
            if pl2 and not pl1:
                ok("PL2 is in force: blocked by %s (paranoia-level/2) alone" % " ".join(pl2))
            else:
                fail("PL2 probe: matched PL1 %s, PL2 %s; expected PL2 rules only" % (pl1, pl2))
for item in failures:
    if isinstance(item, tuple):
        label, method, uri = item
        rules = rules_of(audit.get((method, uri), []))
        print("  FAIL  %s: %s %s blocked by %s" % (label, method, uri.split("?")[0],
                                                  ", ".join(rules) or "no audit line found"))
for what, method, path in sorted(set(leaks)):
    fail("an audit line holds %s (%s %s); the value is not printed" % (what, method, path))
if secrets and not leaks:
    ok("no audit line holds any of the %d secrets of this run (passwords, tokens, tickets, "
       "URL signatures)" % len(secrets))
print("Audit log for this run: %d lines, %d bytes" % (audit_lines, audit_bytes))

failed = len(failures)
print("waf-check: %d probes blocked, %d normal requests passed" % (probes_blocked, normal_passed))
if failed:
    print("waf-check: FAILED (%d %s)" % (failed, "miss" if failed == 1 else "misses"))
    sys.exit(1)
print("waf-check: all checks passed")
PY

echo
./infra/proxy/waf-sweep.sh ci || rc=1
if [ "${WAF_SWEEP:-}" = 1 ]; then
    echo
    ./infra/proxy/waf-sweep.sh all || rc=1
fi
exit "$rc"
