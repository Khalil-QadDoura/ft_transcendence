# WAF: ModSecurity with the OWASP CRS, blocking at paranoia level 2

Card INF-11 (module M13). The front proxy (`infra/proxy/`, nginx + ModSecurity v3.0.17 + OWASP Core Rule Set 4.30.0) blocks requests that look like attacks. This page covers what it inspects, how it is set, every exclusion and why it is safe, how to read its log, and how to demo it. The check is `make waf-check` (`infra/proxy/waf-check.sh`).

## What the WAF sees and does not see

ModSecurity runs inside the proxy on every route of the one origin (`/`, `/api`, `/ws`, `/files`, `/grafana`, `/mail`). For each request it reads:

- the request line: method, path, query string (each parameter is `ARGS:<name>`);
- the request headers, cookies included;
- the request body: JSON is parsed into fields (`ARGS:json.<field>`, arrays as `json.<list>.array_<n>.<field>`), up to 13 MB (`SecRequestBodyLimit`); on `/files` a bigger upload is inspected for its first 13 MB and passed on (`SecRequestBodyLimitAction ProcessPartial`, up to nginx's 60 MB `client_max_body_size`);
- the response headers and the first 1 MB of the response body (outbound rules: leaked errors and source code).

It does **not** see:

- **WebSocket frames.** On `/ws` and `/ws/game` it inspects the handshake (`GET` with the query string and headers) and nothing after the 101: nginx then copies frames both ways without ModSecurity. Game chat (`chat_message` frames on `/ws/game`) and `ping` are never inspected by the WAF. The defence for frame content is in the API: `backend/app/game/chat.py` checks length, emptiness and characters, the text is stored with SQL parameters and React escapes it on display. The same holds for Grafana Live and Mailpit's event socket.
- **Response bodies past 1 MB** (videos, images): passed through.
- **Traffic inside the Docker network** (api ↔ db, worker ↔ minio, Prometheus scrapes): it never goes through the proxy.
- **The password fields** listed under Exclusions: no CRS rule inspects them (approved exception).

## Mode, paranoia level, thresholds

All in `infra/proxy/proxy.env`, read by the image's entrypoint:

| Setting | Value | Meaning |
| --- | --- | --- |
| `MODSEC_RULE_ENGINE` | `On` | Blocking. `DetectionOnly` only logs (the mode until INF-11) |
| `BLOCKING_PARANOIA` | `2` | CRS rules of levels 1 and 2 count toward blocking. Level 1 is the default set with few false positives; level 2 adds stricter rules (more SQL and shell patterns, `{{…}}` template injection, SQL comment sequences), which catch more attacks and more normal text |
| `DETECTION_PARANOIA` | `2` | Equal to blocking: every rule that runs also counts. Higher would log level 3 matches without blocking |
| `ANOMALY_INBOUND` | `5` | A request is refused when its matched rules add up to 5: one critical match (5) blocks; warnings (3) and notices (2) need company |
| `ANOMALY_OUTBOUND` | `4` | A response is cut when its matches add up to 4: one error-level match (a stack trace, an SQL error message) |
| `MODSEC_AUDIT_LOG_PARTS` | `AHZ` | What an audit line holds; never `B`, `I`, `J` or `E` (headers and bodies) |

Both thresholds are the CRS defaults, written out so they are visible and checked. The live values are read back by `make waf-check` from the container (`printenv`, and the generated `/etc/modsecurity.d/modsecurity.conf` and `owasp-crs/crs-setup.conf`), and shown by behaviour: a probe only a level 2 rule matches (`{{x}}`, rule 941380) is blocked.

## Allowed methods and content types

`ALLOWED_METHODS=GET HEAD POST PUT PATCH DELETE`: what the app sends. The API uses `GET`, `POST`, `PATCH` and `DELETE`; uploads `PUT` to presigned `/files` URLs; `HEAD` comes with `GET`; Grafana's UI uses `PATCH` and `DELETE` too. No `OPTIONS`: everything is same-origin, so no CORS preflight. Anything else gets the WAF's 403 (rule 911100). The CRS default was `GET HEAD POST OPTIONS`, which refused every `PATCH`, `PUT` and `DELETE`.

`ALLOWED_REQUEST_CONTENT_TYPE=|application/json| |image/jpeg| |image/png| |image/webp| |video/mp4|`: JSON for the API, Grafana and Mailpit; the avatar and logo types the API accepts (`PICTURE_TYPES` in `backend/app/media/constants.py`); `video/mp4` for intro videos. Forms, multipart, XML and `text/html` get the WAF's 403 (rule 920420). A request without a body has no type and passes. The frontend always sets `application/json` on API bodies, the file type on avatar and logo uploads and `video/mp4` on videos.

## Exclusions

All in `infra/proxy/modsecurity/before-crs.conf`, mounted over the image's `REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`. They run per request, before the CRS, and switch rules off for that request only. `after-crs.conf` (mounted over `RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf`) is empty on purpose: a removal there would hold for every path. The image ships only `.example` copies of both files, so no CRS rule file is replaced.

Rules for every exclusion:

- one path (exact, `@streq`) or one path pattern, and one method; matched on `REQUEST_FILENAME` after `t:urlDecodeUni,t:normalizePath`, so `%2e%2e` or `/api/../grafana/` cannot borrow another path's exclusion;
- the rule ids, and the one field (`ctl:ruleRemoveTargetById=<id>;ARGS:json.<field>`) whenever the false positive is in one field;
- a comment with the traffic, the matched ids (evidence: the audit lines of `make waf-check` and `make grafana-check`) and why it is safe;
- never `ctl:ruleEngine=Off`, never `SecRequestBodyAccess Off`, never 942100 or 941100 (libinjection SQL and XSS) off an API field (the one approved exception is passwords), never a paranoia level 1 rule off free text.

libmodsecurity 3.0.17 does not accept a regular expression as a `ctl:ruleRemoveTargetById` target (`ARGS:/^json\.queries/` stops nginx at start with `emerg`), so array fields are listed one by one (`array_0`, `array_1`).

| Id | Path | Method | Rule ids | Target | Why it is safe | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| 10010 | `/grafana/` (prefix) | any | 953100 (PHP information leakage, outbound) | the response | Grafana's own pages contain text the rule reads as PHP errors; only that outbound rule; every request rule still runs on `/grafana/` | `GET /grafana/login` was cut mid-response (INF-09 review) |
| 10011 | `/grafana/api/ds/query` | `POST` | 932271, 941340, 942100, 942120, 942150, 942200, 942300, 942330, 942410, 942430 | `json.queries.array_0.expr`, `json.queries.array_1.expr` | PromQL (`sum by (handler) (rate(…[5m]))`) looks like SQL and shell; Grafana passes it to Prometheus, a read-only query language with no SQL or shell; admin only; the rest of the body is inspected | every panel of both dashboards, `make waf-check` "Grafana panel …" |
| 10011 | same | same | 941380 (template injection) | `json.queries.array_{0,1}.legendFormat` | `{{handler}}` is Grafana's legend template, rendered by Grafana as text | panels with a legend |
| 10012 | `/grafana/api/snapshots` | `POST` | 932231, 932235, 932236, 932271, 941340, 941380, 942100, 942150, 942180, 942200, 942210, 942300, 942330, 942340, 942370, 942410, 942430, 942510 | the request (dozens of dashboard fields) | Snapshots are off in Grafana: it refuses every one with its own 403 "Dashboard Snapshots are disabled" and stores nothing; admin only. Without it the WAF's HTML 403 hid Grafana's answer | `make grafana-check`, `make waf-check` "Grafana snapshot" |
| 10020 | `/api/users/me` | `PATCH` | 942440, 931130, 932200, 942120, 932231 | `json.bio`; 942440 also on `json.position` | Profile prose (PL2 rules only); stored with SQL parameters, shown escaped by React; every PL1 rule still runs | `make waf-check` "profile text a/b" |
| 10021 | `/api/companies` | `POST` | 942440, 931130, 932200 | `json.description` | as above | "company" |
| 10022 | `/api/jobs` | `POST` | 942440, 931130, 932200 | `json.description` | as above | "job create" |
| 10023 | `^/api/conversations/[0-9]+/messages(/[0-9]+)?$` | `POST`, `PATCH` | 942440, 931130, 932200, 942120, 942200 | `json.content` | Chat messages, send and edit; as above | "message a/b", "message edit" |
| 10024 | `/api/jobs/open` | `GET` | 942440 | `ARGS:keyword` | The search box; the keyword goes to the database as a parameter | "job search" |
| 10030 | `/api/auth/register` | `POST` | every CRS rule (`ruleRemoveTargetByTag=OWASP_CRS`) | `json.password` | see Passwords | "sign up a/b" |
| 10031 | `/api/auth/login` | `POST` | every CRS rule | `json.password` | see Passwords | "login …" |
| 10032 | `/api/auth/change-password` | `POST` | every CRS rule | `json.current_password`, `json.new_password` | see Passwords | "change password a" |
| 10033 | `/api/auth/reset-password` | `POST` | every CRS rule | `json.new_password` | see Passwords | "reset password b" |

What the free-text PL2 rules matched (all paranoia level 2):

| Rule | Name | Matched in normal text |
| --- | --- | --- |
| 942440 | SQL comment sequence | `--` used as a dash: "Senior engineer -- backend" |
| 931130 | Remote file inclusion | any link to another site: `https://example.org/maria` |
| 932200 | RCE bypass technique | "/portfolio?" or "'m … https:/" in a sentence |
| 942120 | SQL operator | Russian text: "Мой сайт: … и телефон" |
| 942200 | MySQL comment / space obfuscation | a sentence with a link, `?`, `&` and `--` |
| 932231 | Unix command injection | a sentence with a link and `--` |

**Free text: a deviation from the brief, approved.** The brief allowed only character-anomaly rules to be lifted from free text. The PO decided (byul-byul, 2026-11-23) to lift, per field and per path and method, exactly the PL2 rules the corpus proves, and no PL1 rule. Every PL1 rule, 942100 and 941100 among them, still runs on bio, descriptions and messages: `' OR 1=1 --` or `<script>` there is still blocked (`make waf-check` probes "SQL injection in a JSON body" and "XSS in a JSON body" hit those very fields).

**Passwords: an explicit exception, approved.** PO decision (byul-byul, 2026-11-23). Every request field that carries a password, from `docs/api/api-contract.md` and `backend/app/auth/schemas.py`: `password` (register, login), `current_password` and `new_password` (change-password), `new_password` (reset-password). There is no other one on main: `DELETE /api/users/me` takes no body, no password confirmation exists yet, and the open PRs add none (checked 2026-11-23). A new one needs its own block in `before-crs.conf` and a line here.

- Why: a password manager's password is random symbols. Sent to login at PL2, of 300 random 16-character passwords over all of `string.punctuation`, 152 got the WAF's 403 (942131, 932240, 942520, 942370, … and in 5 cases level 1 rules such as 942100, 932370, 933100); of 300 like Bitwarden's default (symbols `!@#$%^&*`, 14 characters), 79 (932240, 942131); of 300 like Chrome's (`-_.:!`), none. Those users could neither sign up nor log in. Worse, each matched rule wrote the password in clear into the audit line (`"data": "Matched Data: … found within ARGS:json.password: <password>"`).
- How: `ctl:ruleRemoveTargetByTag=OWASP_CRS;ARGS:json.password`, so no CRS rule reads that one field on that one path and method. The email, the reset `token` and every other field are still inspected by every rule: an SQL injection in the email of a login is still blocked.
- Safe: the API never puts a password into SQL, HTML, a shell or a path. It only hashes it (argon2id) or verifies it against the stored hash, and refuses one longer than 128 characters (422).
- Tested: 0 of the 900 passwords blocked, and none in the audit log. `make waf-check` signs up, logs in, changes and resets passwords with symbols that the WAF blocked before, and fails if any audit line of the run holds a password, a token, a ticket or a URL signature.
- Before this card: in `DetectionOnly` at level 1, a password that matched a level 1 rule was already written in clear into the proxy's audit log (json-file). After the merge, run `make logs-reset` once on every stack that ran the old proxy.

### Known false positives left in place

Each one is a level 1 rule or a level 2 rule the corpus does not justify lifting. The user gets the WAF's 403 page and can rephrase.

- **"part-time work -- weekends only" as a whole field** (a short value: a position, a job title, a search): 942100 (level 1, libinjection) reads `work -- weekends` as SQL with a comment. In a longer sentence ("I'm looking for part-time work -- weekends only.") it passes. 942100 stays: it is the main SQL injection rule.
- **`{{` … `}}` in free text** (941380, level 2, template injection): it is what makes the level 2 probe work, and normal prose rarely has it.
- **`~user/file.pdf` paths in a bio with a link**: 932230 and 932250 (level 1, Unix command injection).
- **Job and company edit (`PATCH /api/jobs/<id>`, `PATCH /api/companies/<id>`)**: no exclusion yet. The edit pages (FE-27, FE-14) are not on main; the same per-field lifts as their `POST` are expected once they ship and waf-check covers them.
- **Grafana `ds/query` with three or more targets in one panel**: only `array_0` and `array_1` are lifted (our panels have one or two). A third target in a new panel would be blocked: add `array_2` lines to id 10011.

## Telling a WAF 403 from an app 403

| | WAF 403 | App 403 (API) | Grafana 403 |
| --- | --- | --- | --- |
| `Content-Type` | `text/html` | `application/json` | `application/json` |
| Body | nginx's page, `<title>403 Forbidden</title>` | `{"error": {"code": "403", "detail": "…"}}` | `{"message": "…"}` |
| `X-Request-ID` | none (the request never reached the API) | yes | — |
| Audit line | yes, with the rule ids and 949110 (score exceeded) | yes, without rule messages (any 4xx but 404 is logged) | yes, without rule messages |

In the browser, a WAF block shows in the Network tab as a 403 with an HTML preview; the frontend reports it as a generic error. `make waf-check`, `make files-check` and `make grafana-check` tell them apart the same way.

## Reading an audit line

One JSON line per audited transaction on the proxy's stdout (`SecAuditLog /dev/stdout`). A transaction is audited when a rule matched, or the answer is a 4xx other than 404, or a 5xx.

```
docker compose logs --no-log-prefix proxy 2>&1 | grep '"transaction"' | tail -1 | python3 -m json.tool
```

Fields (parts `A`, `H`, `Z`):

- `transaction.client_ip`, `time_stamp`, `unique_id`; `request.method`, `request.uri` (with the query string), `request.hostname`; `response.http_code` (403 when the WAF blocked).
- `transaction.messages[]`, one per matched rule: `details.ruleId`; `details.data`, "Matched Data: `<what>` found within `<variable>`: `<value>`", which names the field (`ARGS:json.bio`) an exclusion would target, and holds **a piece of the request** (see Privacy below); `details.severity` (2 critical, 3 error, 4 warning, 5 notice); `details.tags`, with `paranoia-level/N`.
- Rule 949110 "Inbound Anomaly Score Exceeded (Total Score: N)" is the block itself; 980170 sums up for responses.

Example (the level 2 probe, shortened):

```json
{"transaction": {"client_ip": "172.19.0.1", "unique_id": "179540996146.838418",
 "request": {"method": "GET", "uri": "/api/jobs/open?keyword=%7B%7Bx%7D%7D"},
 "response": {"http_code": 403},
 "messages": [
  {"message": "AngularJS client side template injection detected",
   "details": {"ruleId": "941380", "severity": "2",
    "data": "Matched Data: Suspicious payload found within ARGS:keyword: {{x}}",
    "tags": ["attack-xss", "paranoia-level/2", "..."]}},
  {"message": "Inbound Anomaly Score Exceeded (Total Score: 5)", "details": {"ruleId": "949110"}}]}}
```

No line holds request or response headers or bodies (`AHZ`), but `details.data` and `request.uri` hold what matched and the query string. So: no rule may inspect a password (the exception above), and `make waf-check` searches every audit line of its run for the secrets it used.

**Secrets that can still reach an audit line** (checked 2026-11-23; none did in `make waf-check`, which searches for 22 of them per run):

- the WebSocket ticket in the handshake's query string (`/ws?ticket=…`): only if the handshake itself is audited (a rule match or a 4xx; normally 101, not audited). One use, 30 s.
- a presigned URL's `X-Amz-Signature` in `/files/…?…` when the request ends in a 4xx (an expired link, or a WAF block such as the `text/html` upload of `make files-check`, whose signature was still valid for its 15 min).
- the email link token of `/api/auth/verify?token=…` (and the 42 OAuth `code` and `state` of PR #80) when that request gets a 4xx (already used or expired).
- refresh tokens (`refresh_token` in the body of refresh and logout) and the Bearer token, only if a rule matched them: they are base64url, which matched nothing in 300 samples.

Since QA-01 (2026-11-25) the proxy's access log no longer holds these query strings: `/verify-email`, `/reset-password`, `/api/auth/`, `/files/` and `/ws` are logged without their query string (`infra/proxy/templates/conf.d/logging.conf.template`, see the proxy README). The audit line still holds the URI with its query string when a rule matched. Proposal, for the PO (not done here): send the WebSocket ticket in the first frame or the `Sec-WebSocket-Protocol` header instead of the URL.

## Demo

Against the running stack (`make`), from the repository folder:

```
CA=--cacert infra/proxy/certs/server.crt

# SQL injection in a query string: the WAF's 403 (HTML), no X-Request-ID
curl -s $CA -i "https://localhost/api/jobs/open?keyword=1'%20UNION%20SELECT%20password%20FROM%20users--" | head -5

# XSS in a JSON body
curl -s $CA -o /dev/null -w '%{http_code} %{content_type}\n' -X PATCH -H 'Content-Type: application/json' \
  --data '{"bio":"<img src=x onerror=alert(1)>"}' https://localhost/api/users/me

# Level 2 only: 941380 alone blocks it
curl -s $CA -o /dev/null -w '%{http_code}\n' "https://localhost/api/jobs/open?keyword=%7B%7Bx%7D%7D"

# The same text as normal prose passes the WAF (the app answers, here 401 JSON: no token)
curl -s $CA -i -X PATCH -H 'Content-Type: application/json' \
  --data '{"bio":"Senior engineer -- backend. See https://example.org/me"}' https://localhost/api/users/me | head -5

# The audit lines of the last minute: rule ids per request
docker compose logs --no-log-prefix --since 1m proxy 2>&1 | grep '"transaction"' | python3 -c '
import json, sys
for line in sys.stdin:
    t = json.loads(line)["transaction"]
    print(t["response"]["http_code"], t["request"]["method"], t["request"]["uri"][:60],
          [m["details"]["ruleId"] for m in t["messages"]])'
```

Live change for the defense: in `infra/proxy/proxy.env` set `MODSEC_RULE_ENGINE=DetectionOnly`, then `docker compose up -d --force-recreate --wait proxy`. The SQL injection curl now gets the API's answer (JSON 422), and the audit line still lists 942100; `make waf-check` fails on every probe. Set it back to `On` and recreate the proxy.

## `make waf-check`

Runs from the host, over HTTPS through the proxy, with the proxy certificate as the CA (bash and Python 3.9+, standard library only):

1. Configuration: the six settings above in the container's environment, the generated `SecRuleEngine On`, `SecAuditLogParts AHZ` and CRS setup, and both mounted exclusion files equal to the repository's.
2. Seven attack probes, each must get the WAF's 403 and leave an audit line (found by a unique `waf_check=<run>-<n>` query parameter): SQL injection in a query string and in a JSON body, XSS in a query string and in a JSON body, path traversal, a scanner User-Agent (`sqlmap`), and the level 2 probe, which must be blocked by level 2 rules alone.
3. The corpus, which must never get the WAF's 403:
   - two users signed up, verified through Mailpit and logged in, with password-manager passwords; refresh;
   - profile text in English, Russian and Arabic, with quotes, `--`, links and emoji;
   - a company and a job (create, list, read, edit, search);
   - a conversation: send, history, edit, read, delete;
   - avatar and intro video uploads (presigned `PUT`) with their confirm;
   - a game round: queue, start, room, chat history, both WebSocket handshakes (101, and `/ws/game` sends its `game_snapshot` frame), a vote refused with the app's 409, leave;
   - a password change and a reset through the email link; logout; both accounts deleted;
   - Grafana as the browser loads it: the login page, both dashboards, the variable values, every panel's `ds/query`, and the snapshot refusal, with Grafana's own 403.
4. No audit line of the run holds any secret the run used (passwords, tokens, tickets, URL signatures, the Grafana admin password); found by search, never printed.

It ends with `waf-check: N probes blocked, M normal requests passed` and exits 1 on any miss, naming the request and the rule ids with their field (`profile text b: PATCH /api/users/me blocked by 942120 on ARGS, …`). It signs up two users; the API allows 5 sign-ups and 3 forgotten-password emails a minute per IP, so wait a minute between two runs. CI runs it in the `stack` job after `make grafana-check`.

**Negative runs** (2026-11-23):

- `MODSEC_RULE_ENGINE=DetectionOnly`: exit 1, 9 misses: the engine setting and the live `SecRuleEngine On`, and all 7 probes ("0 probes blocked, 70 normal requests passed").
- Exclusion 10020 (profile) commented out: exit 1, "profile text a: PATCH /api/users/me blocked by 931130 on ARGS, 932200 on ARGS, 942440 on MATCHED_VARS, 949110", and for b also 932231 and 942120.
- Exclusions 10030 and 10031 (register and login passwords) commented out: exit 1, "sign up a: POST /api/auth/register blocked by 932240 on ARGS, 942131 on ARGS, 949110", and "an audit line holds a password (POST /api/auth/register); the value is not printed".

## Audit log volume

The proxy logs to Docker's json-file driver, `max-size 10m`, `max-file 3`: at most 30 MB per container (see Logs and retention in [infrastructure.md](infrastructure.md)). Measured on 2026-11-23 with blocking on:

| Run | Audit lines | Bytes |
| --- | --- | --- |
| `make waf-check` | 11 (7 probes, 4 app 4xx: job search 422, vote 409, results 409, Grafana snapshot 403) | about 48 kB |
| `make grafana-check` | 7 (its intended 401s, 400s and the snapshot 403; Grafana Live 920320, no User-Agent, score 2) | about 4.5 kB (65 kB before INF-11, when every panel query matched) |
| `make files-check` | 6 (MinIO's intended 403s, one WAF block of the `text/html` upload) | about 5 kB |
| `make mail-check` | 1 (its intended unverified login, 403 JSON) | about 0.6 kB |
| `make https-check`, `images-check`, `metrics-check` | 0 | 0 |
| An open dashboard | 0 (was about 2.4 kB every 30 s) | 0 |

So about 600 `make waf-check` runs fill the 30 MB, before access lines. An attack scan fills it faster (1 to 12 kB per blocked request); the oldest file then rotates out, and `make logs-reset` empties it.

## Not covered

- WebSocket frames (above).
- Rate limiting and brute force: the API's limits per IP (`docs/api/api-contract.md`), not the WAF. ModSecurity's DoS rules are not enabled.
- Bot detection beyond scanner User-Agents (913100).
- Response bodies past 1 MB, uploaded file content past 13 MB (the API checks pictures with Pillow and videos by their header).
- Levels 3 and 4: not enabled.
- The CRS is pinned with the image (4.30.0); an update means rerunning `make waf-check` and `make grafana-check`.
