#!/usr/bin/env bash
# Smoke test of Grafana (INF-09, module M12), from the host, over HTTPS through the proxy
# only (the proxy's certificate is the trust anchor):
# - /grafana/ without a session redirects to /grafana/login on the public origin, and the
#   login page carries the root URL Grafana builds its links with (FRONTEND_BASE_URL plus
#   /grafana/, the port included when it is not 443);
# - /grafana/api/health answers 200 with the database ok;
# - access: no anonymous access (/api/search without login is 401), sign-up is refused,
#   and the security settings as Grafana reads them (no anonymous access, sign-up or org
#   creation, Secure cookie, brute-force protection on, no usage reports or update checks,
#   public dashboards and external snapshots off); the public-dashboard API answers 404
#   and the snapshot sharing options offer no external publish;
# - the datasource uid prometheus is provisioned (http://prometheus:9090, default,
#   read-only) and its health check reaches Prometheus;
# - the dashboards uid wozu-api and wozu-infra are provisioned in the folder WOZU, every
#   query of every panel returns at least one series with data over the last 15 minutes
#   (sent through Grafana's /api/ds/query, as the browser does, with each dashboard
#   variable such as $project replaced by its current value from the dashboard JSON, the
#   value the browser opens with; that value must be one the variable's own query offers,
#   or the browser would show another), and Grafana refuses to delete them;
# - Grafana Live (WebSocket) answers 101 through the proxy at /grafana/api/live/ws;
# - a login with a wrong password is refused (401).
# Logs in as admin with Basic auth. The password is read from the running container
# (`docker compose exec -T grafana printenv GF_SECURITY_ADMIN_PASSWORD`) into a file only
# this user can read, deleted at the end; it is never printed or put on a command line.
# Brute-force protection: Grafana counts failed logins per username and locks that name
# for 5 minutes after 5 failures within 5 minutes; a later good login does not reset the
# count (the per-IP protection is off by default). The wrong-password check therefore logs
# in as a user that does not exist (grafana-check-nobody), never as admin: any number of
# runs leaves admin's count at zero, so neither the check nor the browser gets locked.
# Retries for up to 60 s (GRAFANA_CHECK_WAIT overrides it), then prints one ok / FAIL line
# per check and exits 1 when one failed.
# Needs the stack up (`make`). Run it with `make grafana-check`. Works with bash 3.2
# (macOS) and python3 3.9 or newer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
CA="$ROOT/infra/proxy/certs/server.crt"
WAIT_SEC="${GRAFANA_CHECK_WAIT:-60}"
RETRY_SEC=5

case "$WAIT_SEC" in
    '' | *[!0-9]*) echo "grafana-check: GRAFANA_CHECK_WAIT must be a number of seconds" >&2; exit 1 ;;
esac
for service in proxy grafana; do
    if [ -z "$(docker compose ps -q --status running "$service")" ]; then
        echo "grafana-check: $service is not running; start the stack with make" >&2
        exit 1
    fi
done

https_port="$(docker compose port proxy 8443)"
https_port="${https_port##*:}"
if [ "$https_port" = 443 ]; then base=https://localhost; else base="https://localhost:$https_port"; fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
chmod 700 "$work"

root_url="$(docker compose exec -T grafana printenv GF_SERVER_ROOT_URL)" || root_url=""
# The password goes straight from the container into a file; only python reads it.
(umask 077; docker compose exec -T grafana printenv GF_SECURITY_ADMIN_PASSWORD >"$work/password") || true
if [ ! -s "$work/password" ]; then
    echo "grafana-check: GF_SECURITY_ADMIN_PASSWORD is empty in the grafana container" >&2
    exit 1
fi

installed="$(docker compose exec -T grafana ls -A /var/lib/grafana/plugins | tr '\n' ' ')" \
    || installed="(cannot list /var/lib/grafana/plugins)"

echo "grafana-check: $base/grafana/ (root URL $root_url), retries for up to ${WAIT_SEC}s"

python3 - "$base" "$root_url" "$CA" "$work/password" "$WAIT_SEC" "$RETRY_SEC" "$installed" <<'PY'
import base64
import hashlib
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

base, root_url, ca, password_file, wait_sec, retry_sec, installed = sys.argv[1:8]
installed = installed.strip()
wait_sec, retry_sec = int(wait_sec), int(retry_sec)
with open(password_file, encoding="utf-8") as f:
    password = f.read().rstrip("\r\n")

GRAFANA = base + "/grafana"
DASHBOARDS = {"wozu-api": "WOZU API", "wozu-infra": "WOZU Infrastructure"}
FOLDER = "WOZU"
DATASOURCE = {"uid": "prometheus", "type": "prometheus", "url": "http://prometheus:9090"}
# The security settings decided for INF-09, as /api/admin/settings returns them.
SETTINGS = [
    ("auth.anonymous", "enabled", "false"),
    ("users", "allow_sign_up", "false"),
    ("users", "allow_org_create", "false"),
    ("security", "cookie_secure", "true"),
    ("security", "disable_gravatar", "true"),
    ("security", "disable_brute_force_login_protection", "false"),
    ("analytics", "reporting_enabled", "false"),
    ("analytics", "check_for_updates", "false"),
    ("analytics", "check_for_plugin_updates", "false"),
    ("news", "news_feed_enabled", "false"),
    ("plugins", "preinstall_disabled", "true"),
    ("public_dashboards", "enabled", "false"),
    ("snapshots", "external_enabled", "false"),
]
TLS = ssl.create_default_context(cafile=ca)


def basic(user, secret):
    return "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


ADMIN = basic("admin", password)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=TLS), NoRedirect)


def http(method, path, auth=None, body=None):
    """(status, headers, text) of one request to Grafana; status 0 when it does not answer."""
    headers = {"Accept": "application/json"}
    data = None
    if auth:
        headers["Authorization"] = auth
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(GRAFANA + path, data=data, headers=headers, method=method)
    try:
        with OPENER.open(request, timeout=15) as answer:
            return answer.status, answer.headers, answer.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read().decode("utf-8", "replace")
    except (OSError, ValueError) as error:
        return 0, {}, str(error)


def as_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def check_entry():
    results = []
    status, headers, _ = http("GET", "/")
    target = urllib.parse.urljoin(GRAFANA + "/", headers.get("Location", "") if headers else "")
    if status in (301, 302, 303, 307, 308):
        results.append((target == GRAFANA + "/login",
                        f"GET /grafana/ without login: {status} to {target}"))
    else:
        results.append((False, f"GET /grafana/ without login: {status}, expected a redirect to /grafana/login"))
    status, _, text = http("GET", "/login")
    expected = GRAFANA + "/"
    found = '"appUrl":"%s"' % expected in text
    results.append((status == 200 and found and root_url == expected,
                    f"GET /grafana/login: {status}, root URL {root_url or '(unset)'}"
                    + ("" if found else f", the page does not carry appUrl {expected}")))
    # The login form's own request: where the browser goes next, and the session cookie.
    status, headers, text = http("POST", "/login", body={"user": "admin", "password": password})
    target = urllib.parse.urljoin(GRAFANA + "/", str((as_json(text) or {}).get("redirectUrl", "")))
    cookies = headers.get_all("Set-Cookie") or [] if headers else []
    session = [c for c in cookies if c.startswith("grafana_session=")]
    secure = bool(session) and all("secure" in [p.strip().lower() for p in c.split(";")] for c in session)
    results.append((status == 200 and target.startswith(expected) and secure,
                    f"POST /grafana/login as admin: {status}, then {target}, session cookie "
                    + ("Secure" if secure else "missing or not Secure")
                    + (" (admin locked by brute-force protection?)" if status == 401 else "")))
    return results


def check_health():
    status, _, text = http("GET", "/api/health")
    body = as_json(text) or {}
    return [(status == 200 and body.get("database") == "ok",
             f"GET /grafana/api/health: {status}, database {body.get('database')}, version {body.get('version')}")]


def check_access():
    results = []
    status, _, _ = http("GET", "/api/search")
    results.append((status == 401, f"GET /grafana/api/search without login: {status} (expected 401)"))
    status, _, text = http("POST", "/api/user/signup", body={"email": "grafana-check@example.com"})
    message = (as_json(text) or {}).get("message")
    results.append((status in (401, 403) and "disabled" in str(message).lower(),
                    f"POST /grafana/api/user/signup: {status} {message}"))
    status, _, text = http("GET", "/api/admin/settings", auth=ADMIN)
    settings = as_json(text)
    if status != 200 or not isinstance(settings, dict):
        results.append((False, f"GET /grafana/api/admin/settings as admin: {status}"
                               + (" (admin locked by brute-force protection?)" if status == 401 else "")))
        return results
    wrong = []
    for section, key, value in SETTINGS:
        actual = str(settings.get(section, {}).get(key, "(unset)")).lower()
        if actual != value:
            wrong.append(f"{section}.{key}={actual} (decided {value})")
    results.append((not wrong, "security settings: " + ("; ".join(wrong) if wrong else
                                                       f"{len(SETTINGS)} as decided (anonymous, sign-up, "
                                                       "org create, Secure cookie, brute-force, analytics, news, plugins, "
                                                       "public dashboards, external snapshots)")))
    # Public dashboards off: the API that gives a dashboard a public link is not there (404).
    # Were it there, the link just made is removed again at once.
    uid = next(iter(DASHBOARDS))
    status, _, text = http("POST", f"/api/dashboards/uid/{uid}/public-dashboards", auth=ADMIN,
                           body={"isEnabled": True, "share": "public"})
    made = (as_json(text) or {}).get("uid") if status == 200 else None
    if made:
        http("DELETE", f"/api/dashboards/uid/{uid}/public-dashboards/{made}", auth=ADMIN)
    results.append((status == 404, f"POST /grafana/api/dashboards/uid/{uid}/public-dashboards: {status} "
                                   + ("(refused, public dashboards are off)" if status == 404 else
                                      f"(expected 404; public link {made} made and removed again)" if made else
                                      f"(expected 404) {(as_json(text) or {}).get('message')}")))
    status, _, text = http("GET", "/api/snapshot/shared-options", auth=ADMIN)
    options = as_json(text) or {}
    results.append((status == 200 and options.get("externalEnabled") is False,
                    f"GET /grafana/api/snapshot/shared-options: {status}, externalEnabled "
                    f"{options.get('externalEnabled')} (expected False: no publish to {options.get('externalSnapshotURL')})"))
    # Plugins that come with the image (the Prometheus datasource among them) load from the
    # image; anything installed or downloaded lands in /var/lib/grafana/plugins.
    results.append((installed == "", "plugins installed in /var/lib/grafana/plugins: " + (installed or "none")))
    return results


def check_datasource():
    results = []
    status, _, text = http("GET", f"/api/datasources/uid/{DATASOURCE['uid']}", auth=ADMIN)
    ds = as_json(text) or {}
    if status != 200:
        return [(False, f"datasource uid {DATASOURCE['uid']}: {status}")]
    problems = [f"expected {k} {DATASOURCE[k]}" for k in ("type", "url") if ds.get(k) != DATASOURCE[k]]
    if not ds.get("isDefault"):
        problems.append("not the default")
    if not ds.get("readOnly"):
        problems.append("editable in the UI")
    results.append((not problems, f"datasource uid {DATASOURCE['uid']}: {ds.get('type')} at {ds.get('url')}"
                                  + (", " + ", ".join(problems) if problems else ", default, read-only")))
    status, _, text = http("GET", f"/api/datasources/uid/{DATASOURCE['uid']}/health", auth=ADMIN)
    body = as_json(text) or {}
    results.append((status == 200 and body.get("status") == "OK",
                    f"datasource uid {DATASOURCE['uid']} health: {status} {body.get('status')} {body.get('message')}"))
    return results


def series_count(answer, ref):
    """Frames of one query of a /api/ds/query answer that hold at least one point."""
    frames = answer.get("results", {}).get(ref, {}).get("frames", [])
    count = 0
    for frame in frames:
        values = frame.get("data", {}).get("values", [])
        if len(values) >= 2 and values[0]:
            count += 1
    return count


VARIABLE = re.compile(r"\$\{(\w+)(?::\w+)?\}|\[\[(\w+)\]\]|\$(\w+)")


def dashboard_variables(dashboard):
    """{name: current value} of the dashboard's variables, as the browser opens it."""
    values = {}
    for variable in dashboard.get("templating", {}).get("list", []):
        current = (variable.get("current") or {}).get("value")
        if isinstance(current, list):
            current = "|".join(current)
        values[variable.get("name")] = current
    return values


LABEL_VALUES = re.compile(r"^\s*label_values\(\s*(?:([^,()]+?)\s*,\s*)?(\w+)\s*\)\s*$")


def variable_options(variable):
    """Values a label_values() query variable offers over the last 15 minutes, as the
    browser's dropdown fetches them (Grafana's datasource resource API); None for any
    other kind of variable."""
    match = LABEL_VALUES.match(variable.get("definition") or "")
    if variable.get("type") != "query" or not match:
        return None
    metric, label = match.groups()
    now = int(time.time())
    params = {"start": now - 900, "end": now}
    if metric:
        params["match[]"] = metric
    status, _, text = http("GET", f"/api/datasources/uid/{DATASOURCE['uid']}/resources/api/v1/label/{label}/values?"
                           + urllib.parse.urlencode(params), auth=ADMIN)
    return (as_json(text) or {}).get("data") or [] if status == 200 else []


def substitute(expr, values):
    """expr with $name, ${name} and [[name]] replaced by the current value; others kept."""
    def value(match):
        name = next(group for group in match.groups() if group)
        return values[name] if values.get(name) is not None else match.group(0)
    return VARIABLE.sub(value, expr)


def check_dashboards():
    results = []
    for uid, title in DASHBOARDS.items():
        status, _, text = http("GET", f"/api/dashboards/uid/{uid}", auth=ADMIN)
        answer = as_json(text) or {}
        meta, dashboard = answer.get("meta", {}), answer.get("dashboard", {})
        if status != 200:
            results.append((False, f"dashboard {uid}: {status}"))
            continue
        ok = meta.get("folderTitle") == FOLDER and meta.get("provisioned") and dashboard.get("title") == title
        results.append((bool(ok), f"dashboard {uid} \"{dashboard.get('title')}\": folder {meta.get('folderTitle')},"
                                  f" provisioned {bool(meta.get('provisioned'))}"))
        variables = dashboard_variables(dashboard)
        # The browser refreshes a query variable when the dashboard opens and, when the saved
        # value is not among the answers, shows the first answer instead: so the saved value
        # must be one of them for the panels below to be what the browser shows.
        for variable in dashboard.get("templating", {}).get("list", []):
            name, value = variable.get("name"), variables.get(variable.get("name"))
            options = variable_options(variable)
            ok = bool(value) and (options is None or value in options)
            results.append((ok, f"dashboard {uid} variable {name}: current {value or '(none)'}"
                                + ("" if options is None else f", offered {', '.join(options) or '(nothing)'}")))
        for panel in dashboard.get("panels", []):
            for target in panel.get("targets", []):
                ref = target.get("refId", "A")
                ds_uid = (target.get("datasource") or panel.get("datasource") or {}).get("uid")
                query = {"refId": ref, "datasource": {"type": "prometheus", "uid": ds_uid},
                         "expr": substitute(target.get("expr", ""), variables), "range": True, "instant": False,
                         "intervalMs": 15000, "maxDataPoints": 100}
                status, _, text = http("POST", "/api/ds/query", auth=ADMIN,
                                       body={"queries": [query], "from": "now-15m", "to": "now"})
                answer = as_json(text) or {}
                error = answer.get("results", {}).get(ref, {}).get("error") or answer.get("message")
                count = series_count(answer, ref) if status == 200 else 0
                label = f"{uid} / {panel.get('title')} / {ref}"
                used = sorted(name for name in variables if re.search(
                    r"\$\{%s[:}]|\[\[%s\]\]|\$%s\b" % ((re.escape(name),) * 3), target.get("expr", "")))
                if used:
                    label += " (" + ", ".join(f"{name}={variables[name]}" for name in used) + ")"
                if ds_uid != DATASOURCE["uid"]:
                    results.append((False, f"{label}: datasource uid {ds_uid}, expected {DATASOURCE['uid']}"))
                else:
                    results.append((count >= 1, f"{label}: {count} series over 15 min"
                                                + (f" ({status} {error})" if count < 1 else "")))
    return results


def check_delete_refused():
    results = []
    for uid in DASHBOARDS:
        status, _, text = http("DELETE", f"/api/dashboards/uid/{uid}", auth=ADMIN)
        message = (as_json(text) or {}).get("message")
        after, _, _ = http("GET", f"/api/dashboards/uid/{uid}", auth=ADMIN)
        results.append((status >= 400 and after == 200,
                        f"DELETE dashboard {uid}: {status} {message}; still there: {after == 200}"))
    return results


def check_live():
    """WebSocket handshake to Grafana Live through the proxy, as admin."""
    url = urllib.parse.urlsplit(GRAFANA + "/api/live/ws")
    key = base64.b64encode(os.urandom(16)).decode()
    accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    request = (f"GET {url.path} HTTP/1.1\r\nHost: {url.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\nOrigin: {base}\r\n"
               f"Authorization: {ADMIN}\r\n\r\n")
    try:
        with socket.create_connection((url.hostname, url.port or 443), timeout=10) as raw:
            with TLS.wrap_socket(raw, server_hostname=url.hostname) as tls:
                tls.sendall(request.encode())
                head = b""
                while b"\r\n\r\n" not in head and len(head) < 8192:
                    chunk = tls.recv(1024)
                    if not chunk:
                        break
                    head += chunk
    except OSError as error:
        return [(False, f"wss://.../grafana/api/live/ws: {error}")]
    lines = head.split(b"\r\n\r\n")[0].decode("latin-1").split("\r\n")
    status = lines[0] if lines else "(no answer)"
    got = ""
    for header in lines[1:]:
        name, _, value = header.partition(":")
        if name.strip().lower() == "sec-websocket-accept":
            got = value.strip()
    code = status.split()[1] if len(status.split()) > 1 else ""
    return [(code == "101" and got == accept,
             f"wss://.../grafana/api/live/ws as admin: {status.strip()}"
             + (", Sec-WebSocket-Accept matches" if got == accept else ", no matching Sec-WebSocket-Accept"))]


def run_all():
    results = []
    for check in (check_entry, check_health, check_access, check_datasource, check_dashboards,
                  check_delete_refused, check_live):
        results.extend(check())
    return results


started = time.time()
while True:
    results = run_all()
    failures = sum(1 for ok, _ in results if not ok)
    elapsed = time.time() - started
    if failures == 0 or elapsed + retry_sec > wait_sec:
        break
    print(f"grafana-check: {failures} checks not ok yet after {elapsed:.0f}s, retrying in {retry_sec}s",
          flush=True)
    time.sleep(retry_sec)

# A wrong password for a user that does not exist, so admin's failed-login count stays at
# zero (see the brute-force note at the top). Runs last.
NOBODY = "grafana-check-nobody"
wrong = "not-the-password-" + os.urandom(6).hex()
status, _, _ = http("GET", "/api/user", auth=basic(NOBODY, wrong))
results.append((status == 401, f"GET /grafana/api/user as {NOBODY} with a wrong password: {status} (expected 401)"))

for ok, text in results:
    print(f"  {'ok  ' if ok else 'FAIL'}  {text}")
failures = sum(1 for ok, _ in results if not ok)
if failures:
    print(f"grafana-check: {failures} checks failed")
    sys.exit(1)
print("grafana-check: all checks passed")
PY
