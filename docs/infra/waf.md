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
- **A token field whose value has exactly the server's format** (Token fields below): no CRS rule inspects it (approved exception). Any other value in it is inspected by every rule.

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
- never `ctl:ruleEngine=Off`, never `SecRequestBodyAccess Off`, never 942100 or 941100 (libinjection SQL and XSS) off an API field (approved exceptions: password fields; token fields whose value has the exact server format), never a paranoia level 1 rule off free text.

libmodsecurity 3.0.17 does not accept a regular expression as a `ctl:ruleRemoveTargetById` target (`ARGS:/^json\.queries/` stops nginx at start with `emerg`), so array fields are listed one by one (`array_0`, `array_1`).

| Id | Path | Method | Rule ids | Target | Why it is safe | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| 10010 | `/grafana/` (prefix) | any | 953100 (PHP information leakage, outbound) | the response | Grafana's own pages contain text the rule reads as PHP errors; only that outbound rule; every request rule still runs on `/grafana/` | `GET /grafana/login` was cut mid-response (INF-09 review) |
| 10011 | `/grafana/api/ds/query` | `POST` | 932271, 941340, 942100, 942120, 942150, 942200, 942300, 942330, 942410, 942430 | `json.queries.array_0.expr`, `json.queries.array_1.expr` | PromQL (`sum by (handler) (rate(…[5m]))`) looks like SQL and shell; Grafana passes it to Prometheus, a read-only query language with no SQL or shell; admin only; the rest of the body is inspected | every panel of both dashboards, `make waf-check` "Grafana panel …" |
| 10011 | same | same | 941380 (template injection) | `json.queries.array_{0,1}.legendFormat` | `{{handler}}` is Grafana's legend template, rendered by Grafana as text | panels with a legend |
| 10012 | `/grafana/api/snapshots` | `POST` | 932231, 932235, 932236, 932271, 941340, 941380, 942100, 942150, 942180, 942200, 942210, 942300, 942330, 942340, 942370, 942410, 942430, 942510 | the request (dozens of dashboard fields) | Snapshots are off in Grafana: it refuses every one with its own 403 "Dashboard Snapshots are disabled" and stores nothing; admin only. Without it the WAF's HTML 403 hid Grafana's answer | `make grafana-check`, `make waf-check` "Grafana snapshot" |
| 10020–10029 | the free-text fields (next table) | each its own | 942390, 942440, 942120, 942300, 942520, 931130, 932200, 932236, 932240; also 932231 on `bio`, 942200 on `content` | each field by name | Prose (paranoia level 2 rules only); stored with SQL parameters, shown escaped by React; every level 1 rule still runs, so `' OR 1=1 --` and `<script>` are still blocked there | see Free text |
| 10040 | `^/(api/\|ws(/\|$))` | any | 932206 (Unix command injection in the Referer) | the `Referer` header | see Referer | see Referer |
| 10030 | `/api/auth/register` | `POST` | every CRS rule (`ruleRemoveTargetByTag=OWASP_CRS`) | `json.password` | see Passwords | "sign up a/b" |
| 10031 | `/api/auth/login` | `POST` | every CRS rule | `json.password` | see Passwords | "login …" |
| 10032 | `/api/auth/change-password` | `POST` | every CRS rule | `json.current_password`, `json.new_password` | see Passwords | "change password a" |
| 10033 | `/api/auth/reset-password` | `POST` | every CRS rule | `json.new_password` | see Passwords | "reset password b" |
| 10050–10059 | the token fields (see Token fields) | each its own | every CRS rule, **only when the value has the server's exact format** | each field by name | see Token fields | see Token fields |

The free-text fields: every field on main where people type sentences (`backend/app/*/schemas.py`).

| Id | Path | Method | Fields |
| --- | --- | --- | --- |
| 10020 | `/api/users/me` | `PATCH` | `json.first_name`, `json.last_name`, `json.position`, `json.bio` |
| 10021 | `/api/companies` | `POST` | `json.name`, `json.description`, `json.country`, `json.city`, `json.district` |
| 10022 | `/api/jobs` | `POST` | `json.title`, `json.description`, `json.location` |
| 10023 | `^/api/conversations/[0-9]+/messages(/[0-9]+)?$` | `POST`, `PATCH` | `json.content` (send and edit) |
| 10024 | `/api/jobs/open` | `GET` | `ARGS:keyword`, `ARGS:position` (the search) |
| 10025 | `/api/companies/me` | `PATCH` | `json.name`, `json.country`, `json.city`, `json.district` (the schema has no description) |
| 10026 | `^/api/jobs/[0-9]+$` | `PATCH` | `json.title`, `json.description`, `json.location` |
| 10027 | `^/api/jobs/[0-9]+/apply$` | `POST` | `json.cover_note` (BE-28) |
| 10028 | `^/api/applications/[0-9]+/status$` | `PATCH` | `json.note` (BE-28) |
| 10029 | `/jobs` (the frontend page) | `GET` | `ARGS:keyword`, `ARGS:position` (the search kept in the page's URL, sent on a reload) |

What the free-text rules matched (all paranoia level 2, checked by their `paranoia-level/2` tag in the CRS files):

| Rule | Name | Matched in normal text |
| --- | --- | --- |
| 942390 | SQL injection | "or" between two numbers: "I'm free at 10 or 11", "We hire 2 or 3 people each year" |
| 942440 | SQL comment sequence | `--` used as a dash: "senior engineer -- backend" |
| 942120 | SQL operator | Russian and other Cyrillic text: "Инженер-программист" |
| 942300, 942520 | SQL with quotes | a quoted word followed by `--`: moved to "interview" -- see you on Sunday |
| 931130 | Remote file inclusion | any link to another site: `https://example.org/maria` |
| 932200 | RCE bypass technique | "/portfolio?" or "'m … https:/" in a sentence |
| 932236 | Unix command injection | a command name as a word: "Yes, I'm in", "Yes or no?" |
| 932240 | Unix command evasion | apostrophes inside words: "O'Brien's team lead" |
| 942200 | MySQL comment / space obfuscation | a message with a link, `?`, `&` and `--` (`content` only) |
| 932231 | Unix command injection | a bio with a link and `--` (`bio` only) |

**Free text: a deviation from the brief, approved.** The brief allowed only character-anomaly rules to be lifted from free text. The PO decided (byul-byul, 2026-11-23) to lift, per field and per path and method, exactly the PL2 rules the corpus proves, and no PL1 rule. Every PL1 rule, 942100 and 941100 among them, still runs on every free-text field: `' OR 1=1 --` or `<script>` there is still blocked.

Evidence (`infra/proxy/waf-sweep.sh corpus`, see Sweeps): the 170 sentences of `infra/proxy/waf-corpus.txt` (everyday chat, profile, job and application texts in English, Russian, Arabic, Azerbaijani and Turkish, including every example of the #94 review) sent through each of the 27 free-text fields above, 4,590 requests.

| Fields | WAF 403 per field before (5677a35, of 170 sentences) | After |
| --- | --- | --- |
| 20 fields: first and last name; company name, country, city, district (create and edit); job title and location (create and edit), job description (edit); cover note; status note; `position` of the search; both fields of the `/jobs` page | 57 | 2 |
| profile `position`, `keyword` of the API search | 42 | 2 |
| company and job `description` (create) | 31 | 2 |
| `bio`, message `content` (send and edit) | 23 | 2 |
| **All 27 fields, 4,590 requests** | **1,355** | **54** |

The 54 left are 942100 (level 1) on the two accepted sentences, in all 27 fields (see Known false positives). Sentences matched per rule before: 942440 20, 942390 16, 931130 11, 942120 8, 932200 7, 932236 3, 932240 2, 942300 and 942520 1 (plus 942100 on the 2 accepted ones).

The same sweep sends `' OR 1=1 --`, `<script>alert(1)</script>` and `1 UNION SELECT password FROM users--` in each of the 27 fields: 81 of 81 get the WAF's 403, before and after.

**Passwords: an explicit exception, approved.** PO decision (byul-byul, 2026-11-23). Every request field that carries a password, from `docs/api/api-contract.md` and `backend/app/auth/schemas.py`: `password` (register, login), `current_password` and `new_password` (change-password), `new_password` (reset-password). There is no other one on main: `DELETE /api/users/me` takes no body, no password confirmation exists yet, and the open PRs add none (checked 2026-11-23). A new one needs its own block in `before-crs.conf` and a line here.

- Why: a password manager's password is random symbols. Sent to login at PL2, of 300 random 16-character passwords over all of `string.punctuation`, 152 got the WAF's 403 (942131, 932240, 942520, 942370, … and in 5 cases level 1 rules such as 942100, 932370, 933100); of 300 like Bitwarden's default (symbols `!@#$%^&*`, 14 characters), 79 (932240, 942131); of 300 like Chrome's (`-_.:!`), none. Those users could neither sign up nor log in. Worse, each matched rule wrote the password in clear into the audit line (`"data": "Matched Data: … found within ARGS:json.password: <password>"`).
- How: `ctl:ruleRemoveTargetByTag=OWASP_CRS;ARGS:json.password`, so no CRS rule reads that one field on that one path and method. The email and every other field are still inspected by every rule (the reset `token` too, unless it has the server's exact format: Token fields): an SQL injection in the email of a login is still blocked.
- Safe: the API never puts a password into SQL, HTML, a shell or a path. It only hashes it (argon2id) or verifies it against the stored hash, and refuses one longer than 128 characters (422).
- Tested: 0 of the 900 passwords blocked, and none in the audit log. `make waf-check` signs up, logs in, changes and resets passwords with symbols that the WAF blocked before, and fails if any audit line of the run holds a password, a token, a ticket or a URL signature.
- Before this card: in `DetectionOnly` at level 1, a password that matched a level 1 rule was already written in clear into the proxy's audit log (json-file). After the merge, run `make logs-reset` once on every stack that ran the old proxy.

### Referer

Rule 932206 (Unix command injection, paranoia level 2) reads only the `Referer` header. A browser sends the page's URL there, and the jobs page keeps its search in its URL, so the search's own call, `GET /api/jobs/open` with `Referer: https://localhost/jobs?keyword=backend+developer`, got the WAF's 403 (#94 review). Two changes:

- **The pages send `Referrer-Policy: strict-origin`** (`add_header` in `location /` of `infra/proxy/templates/conf.d/default.conf.template`). The browser then sends only `https://<host>/` as Referer, never a page's query (a search, a reset link's token): not to our API, not to MinIO, not to another site. No `add_header` is set at server or http level, so this one drops none; the API's own `Referrer-Policy` on its auth answers (`backend/app/auth/routes.py`) is unchanged.
- **Exclusion 10040 removes 932206 on `/api/…` and `/ws…`.** The app never reads the Referer (no backend code uses it), so nothing in it reaches a command or a query. Every other rule still reads the header.

Not lifted on the pages: a page request whose Referer is a full URL still meets 932206. Our pages now send only their origin, and other sites' pages send only theirs by default (`strict-origin-when-cross-origin`). A browser that ignores the policy is the only way left to hit it (see Known false positives).

Evidence: with the old config, `/api/jobs/open` with that Referer got the WAF's 403 (932206), and with the origin only, 200. Now it gets 200 JSON, and `GET /` answers with `Referrer-Policy: strict-origin`. `make waf-check` checks both.

### Token fields

The server's random tokens sometimes look like SQL to the CRS. **Second explicit exception to "never 942100 or 941100 off an API field"**, PO decision (byul-byul, 2026-11-25): a token field skips every CRS rule only when its value has exactly the format the server generates, checked by the WAF itself. Any other value in that field keeps every rule, 942100 and 941100 included. This replaces the "refresh_token: no exclusion" of the first version of this card.

**What was blocked.** `infra/proxy/waf-sweep.sh tokens` (see Sweeps) made each kind of token the way the backend makes it and sent it wherever it travels.

- **942100 (libinjection, level 1)** reads a value matching `^[0-9]+-.*--` as "a number minus something, then an SQL comment". `secrets.token_urlsafe` writes A–Z, a–z, 0–9, `-` and `_`, so this happens by chance. Out of 2,000,000 generated values per kind, it hit about 1 reset token in 24,000 (`token_urlsafe(48)`) and about 1 WebSocket ticket or OAuth state in 36,000 (`token_urlsafe(32)`). Hand-made values confirm the pattern: `5-abcd…WX--yz…`, `5--abcd…` and `87--abcd…` are blocked; `a5-abcd…--yz…` (starts with a letter), `5-abcd…-yz…` (no `--`) and `abcd5--EF…` pass. The JWTs start with `eyJ` and never match.
- **Level 2 rules** 942210 (chained SQL injection), 942450 (SQL hex encoding, `0x…`, e.g. `HcEKS-GyS5-0xb09…`), 932236 (Unix command, e.g. `PIPRnP-…` read as `pip`) and 942120 (SQL operator) blocked more, the JWTs too.
- In 202,000 values per kind, these were blocked: WebSocket ticket 14 (942210 6, 942450 4, 942100 3, 932236 1); reset token 26 (942210 11, 942100 7, 942450 7, 932236 1); email verify JWT 12 (942450 7, 942210 5); refresh JWT 12 (942210 6, 942450 6); OAuth state 23 (942210 7, 942100 6, 942450 5, 932236 4, 942120 1). 42's `code` (64 hex characters) had none.

A blocked reset link cannot be used (a new email is needed), a blocked ticket fails one WebSocket connect, and a blocked state fails one 42 login.

**The formats**, verified in the generating code:

| Id | Request | Field | Format (`@rx`) | Made by |
| --- | --- | --- | --- | --- |
| 10050 | `GET /ws` | `ARGS:ticket` | `^[A-Za-z0-9_-]{43}\z` | `secrets.token_urlsafe(32)`, `backend/app/realtime/service.py` |
| 10051 | `GET /ws/game` | `ARGS:ticket` | same | same ticket |
| 10052 | `GET /api/auth/oauth/42/callback` | `ARGS:state` | same | `new_oauth_state()`, `token_urlsafe(32)`, `backend/app/auth/security.py` |
| 10053 | same | `REQUEST_COOKIES:oauth42_state` | same | the same state, in its cookie |
| 10054 | `POST /api/auth/reset-password` | `ARGS:json.token` | `^[A-Za-z0-9_-]{64}\z` | `new_reset_token()`, `token_urlsafe(48)` |
| 10055 | `GET /reset-password` (page) | `ARGS:token` | same | the email's link |
| 10056 | `GET /api/auth/verify` | `ARGS:token` | `^(?=[A-Za-z0-9_.-]{1,290}\z)[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}\z` | `create_token(…, email_verify, ver=…)`, HS256 |
| 10057 | `GET /verify-email` (page) | `ARGS:token` | same | the email's link |
| 10058 | `POST /api/auth/refresh` | `ARGS:json.refresh_token` | as 10056 with `{1,260}` | `create_token(…, refresh)`, HS256 |
| 10059 | `POST /api/auth/logout` | `ARGS:json.refresh_token` | same | same |

Lengths: 32 and 48 random bytes in base64url without padding are exactly 43 and 64 characters. An HS256 signature is 32 bytes, so always 43 characters. The longest real email verify token is 273 characters: `sub` at the BigInteger maximum (19 digits) and `ver` at the integer maximum. The longest refresh token is 244. The caps are 290 and 260, and the boundary was tested: a JWT that 942450 blocks passes at 290 characters and is blocked at 291; for refresh, 260 and 261. The two frontend pages are included because the email's link opens them with the token in the query, and that page request met the same rules.

**How a block works** (`infra/proxy/modsecurity/before-crs.conf`, section "tokens"):

```
SecRule REQUEST_FILENAME "@streq /ws" "id:10050,phase:2,pass,nolog,t:none,t:urlDecodeUni,t:normalizePath,chain"
    SecRule REQUEST_METHOD "@streq GET" "t:none,chain"
        SecRule &ARGS:ticket "@eq 1" "chain"
            SecRule ARGS:ticket "@rx ^[A-Za-z0-9_-]{43}\z" "t:none,ctl:ruleRemoveTargetByTag=OWASP_CRS;ARGS:ticket"
```

- **Phase 2** is when the JSON body has been parsed. This file is loaded before every CRS file, so within phase 2 these rules run before the CRS rules. Every rule that ever matched a token (942xxx, 932xxx) is a phase 2 rule. All 424 CRS request rules carry the tag `OWASP_CRS`. The proof that the lift comes first is behavioural: if it ran after 942100, the score would already be 5 and the request blocked.
- **`&ARGS:<name> @eq 1`**: exactly one value under that name, counting the query and the body together. `?ticket=<valid>&ticket=' OR 1=1 --`, a duplicate JSON key and `ticket=<valid>&Ticket=…` get no lift and are blocked.
- **`\z`, not `$`**: in PCRE, `$` also matches before a final newline. With `$`, a reset token followed by `"\n"` got the lift (tested); with `\z` it does not.
- The `ctl` removes that one target from every CRS rule; every other field of the request is still inspected.

**Why it is safe.** Only the server's alphabet at the exact length passes, which leaves no room for a quote, a space, `<`, `;` or any SQL, HTML or shell syntax. And the API never puts these values into SQL, HTML, a shell or a path. It looks a ticket up in Redis (`realtime/repository.py`), compares a state with its cookie, hashes a reset token with SHA-256 before the database lookup, and verifies a JWT's signature before it reads it.

**Evidence** (2026-11-25):

Sent through the real requests (`infra/proxy/waf-sweep.sh tokens 2000 200000`): per kind, 2,000 values made like the server makes them, each in all of its places (ticket in `/ws` and `/ws/game`, reset token in the API and the page, and so on), and 200,000 more tested offline against the 548 compilable CRS regexes of levels 1 and 2, every value that matched one sent for real.

| Kind | Before: values with the WAF's 403 (of 202,000) | Offline candidates sent | After: WAF 403 |
| --- | --- | --- | --- |
| WebSocket ticket | 14 | 530 | 0 |
| reset token | 26 | 1,108 | 0 |
| email verify JWT | 12 | 515 | 0 |
| refresh JWT | 12 | 520 | 0 |
| OAuth state (query and cookie) | 23 | 489 | 0 |

- The 16 values that 942100 blocked (3 tickets, 7 reset tokens, 6 states) and the 24 JWTs that level 2 rules blocked now pass, in every place they travel.
- Still the WAF's 403 in each of the 10 token fields: `' OR 1=1 --`, `<script>alert(1)</script>`, and a value of the right length with a space or a quote in it (46 of 46 probes, with a duplicate name in each query field). Checked by hand: a 44-character ticket, a 63-character reset token, a token followed by a newline, a JWT one character over its cap, a duplicate JSON key, a capital `Ticket` next to a valid `ticket`, an off-format `oauth42_state` cookie.

**A later backend option**: tokens made with `secrets.token_hex` (0–9 and a–f only) would never match these rules (42's hex `code` never did), and these blocks could go. It is a backend change, not part of this card.

### Known false positives left in place

The ones in everyday text are level 1 rules, which are never lifted from free text. The user gets the WAF's 403, which the frontend shows as "This text was blocked by the security filter. Please rephrase it and try again." (see below), and can rephrase.

- **"Hi Мария! مرحبا 👋 See you at 10 or 11"**: 942100 (libinjection) reads `! … 10 or 11` as SQL. "Hi! See you at 10 or 11" passes, and so does "I'm free at 10 or 11". Blocked in every free-text field.
- **"Part-time iş -- yalnız həftəsonu"**: 942100 reads the hyphenated word, the short word and `--` as SQL with a comment. "iş -- yalnız" passes. Blocked in every free-text field.
- **"part-time work -- weekends only" as a whole short field** (a position, a job title, a search): 942100, as above. In a longer sentence ("I'm looking for part-time work -- weekends only, near Al Reem") it passes.
- **`{{` … `}}` in free text** (941380, level 2, template injection): not lifted, since no everyday sentence in the corpus has it. It is what makes the level 2 probe work.
- **`~user/file.pdf` paths in a bio with a link**: 932230 and 932250 (level 1, Unix command injection).
- **A page request with a full-URL Referer** (only from a browser that ignores `Referrer-Policy`): 932206 is lifted on the API and the WebSockets only.
- **Grafana `ds/query` with three or more targets in one panel**: only `array_0` and `array_1` are lifted (our panels have one or two). A third target in a new panel would be blocked: add `array_2` lines to id 10011.

## Telling a WAF 403 from an app 403

| | WAF 403 | App 403 (API) | Grafana 403 |
| --- | --- | --- | --- |
| `Content-Type` | `text/html` | `application/json` | `application/json` |
| Body | nginx's page, `<title>403 Forbidden</title>` | `{"error": {"code": "403", "detail": "…"}}` | `{"message": "…"}` |
| `X-Request-ID` | none (the request never reached the API) | yes | — |
| Audit line | yes, with the rule ids and 949110 (score exceeded) | yes, without rule messages (any 4xx but 404 is logged) | yes, without rule messages |

In the browser, a WAF block shows in the Network tab as a 403 with an HTML preview. `make waf-check`, `make files-check` and `make grafana-check` tell them apart the same way.

**What the user sees.** The frontend's API client (`frontend/src/api/client.ts`, FE-20) turns a 403 whose `Content-Type` is `text/html` into an error with the code `waf_blocked` and the translated text `common:wafBlocked`. In English: "This text was blocked by the security filter. Please rephrase it and try again." The text exists in all five languages, and `npm run i18n:check` checks them. The API's own 403s are JSON and keep their detail. Screens that print the API error's message show it. Chat send marks the message as failed, and the profile and company forms show their own fixed error text, so they do not show it yet (frontend work outside this card).

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
- refresh tokens (`refresh_token` in the body of refresh and logout), reset tokens and the other token fields, only if a rule matched them. A value in the server's exact format is no longer inspected (Token fields), so it never reaches `details.data`; before this, about 1 value in 8,000 to 17,000 per kind matched a rule. The Bearer token is in a header that no rule matched in the sweeps.

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

1. Configuration: the six settings above in the container's environment, the generated `SecRuleEngine On`, `SecAuditLogParts AHZ` and CRS setup, both mounted exclusion files equal to the repository's, and `GET /` answering with `Referrer-Policy: strict-origin`.
2. Seven attack probes, each must get the WAF's 403 and leave an audit line (found by a unique `waf_check=<run>-<n>` query parameter): SQL injection in a query string and in a JSON body, XSS in a query string and in a JSON body, path traversal, a scanner User-Agent (`sqlmap`), and the level 2 probe, which must be blocked by level 2 rules alone.
3. The corpus, which must never get the WAF's 403:
   - two users signed up, verified through Mailpit and logged in, with password-manager passwords; refresh;
   - profile text in English, Russian and Arabic, with quotes, `--`, links and emoji;
   - a company and a job (create, list, read, edit with free text, search), the company edited, and the search sent with a full-URL `Referer` (see Referer);
   - a conversation: send, history, edit, read, delete;
   - avatar and intro video uploads (presigned `PUT`) with their confirm;
   - a game round: queue, start, room, chat history, both WebSocket handshakes (101, and `/ws/game` sends its `game_snapshot` frame), a vote refused with the app's 409, leave;
   - a password change and a reset through the email link; logout; both accounts deleted;
   - Grafana as the browser loads it: the login page, both dashboards, the variable values, every panel's `ds/query`, and the snapshot refusal, with Grafana's own 403.
4. No audit line of the run holds any secret the run used (passwords, tokens, tickets, URL signatures, the Grafana admin password); found by search, never printed.
5. `infra/proxy/waf-sweep.sh ci` (see Sweeps), about 1,000 requests in a few seconds: the 32 starred sentences of the corpus in all 27 free-text fields (no WAF 403 allowed), one once-blocked value and one fresh value of each kind in each of the 10 token fields (must pass), 46 probes in the token fields and 81 in the free-text fields (each must get the WAF's 403).

`WAF_SWEEP=1 make waf-check` also runs the full sweep (`waf-sweep.sh all`, about 3 minutes, manual only).

Part 1 to 4 ends with `waf-check: N probes blocked, M normal requests passed` (2026-11-25: 7 and 81), part 5 with `waf-sweep: all checks passed`; it exits 1 on any miss, naming the request and the rule ids with their field (`profile text b: PATCH /api/users/me blocked by 942120 on ARGS, …`). It signs up two users; the API allows 5 sign-ups and 3 forgotten-password emails a minute per IP, so wait a minute between two runs. CI runs it in the `stack` job after `make grafana-check`.

**Negative runs** (2026-11-25, each restored and rechecked afterwards):

- 942390 removed from `json.content` in 10023: exit 1, 8 lines like `FAIL  POST /api/conversations/<id>/messages content: "I'm free at 10 or 11" -> WAF 403, blocked by 942390 (PL2) on ARGS:json.content`.
- The `Referrer-Policy` line removed from the template: exit 1, `FAIL  GET / sends Referrer-Policy: None, expected strict-origin`.
- `{43}` changed to `{44}` in 10050: exit 1, `FAIL  token 2-Cmqkh1f4… in GET /ws ARGS:ticket -> WAF 403, blocked by 942100 (PL1) on ARGS:ticket`.

**Negative runs** (2026-11-23):

- `MODSEC_RULE_ENGINE=DetectionOnly`: exit 1, 9 misses: the engine setting and the live `SecRuleEngine On`, and all 7 probes ("0 probes blocked, 70 normal requests passed").
- Exclusion 10020 (profile) commented out: exit 1, "profile text a: PATCH /api/users/me blocked by 931130 on ARGS, 932200 on ARGS, 942440 on MATCHED_VARS, 949110", and for b also 932231 and 942120.
- Exclusions 10030 and 10031 (register and login passwords) commented out: exit 1, "sign up a: POST /api/auth/register blocked by 932240 on ARGS, 942131 on ARGS, 949110", and "an audit line holds a password (POST /api/auth/register); the value is not printed".

## Sweeps

`infra/proxy/waf-sweep.sh` (bash and Python, standard library only; it signs up and deletes its own users through Mailpit) has four modes:

| Mode | What it sends | Time |
| --- | --- | --- |
| `ci` (part of `make waf-check`) | the starred corpus subset, the token samples, the token probes, the free-text probes | a few seconds |
| `corpus` | every line of `infra/proxy/waf-corpus.txt` through every free-text field (4,590 requests), then the 81 free-text probes | about 10 s |
| `tokens [N] [M]` | per kind, N values (default 2,000) sent in all their places, and M more (default 200,000) tested offline against the CRS regexes, every match sent; then the samples and the token probes | about 3 min at the defaults |
| `all` | `corpus`, then `tokens` | about 3 min |

- **The offline pre-screen**: the script copies the CRS request rules of levels 1 and 2 out of the container, compiles the regexes Python can read (548; 4 cannot be, and are covered by the values sent), and runs the generated values through them. libinjection (942100, 941100) has no regex: it is covered by the values sent and by the pattern above.
- **What counts**: a 403 with an HTML body (the WAF). The API's JSON errors and its 429 rate limit mean the WAF let the request through, since the WAF answers before the request reaches the API.
- **The report**: `WAF_SWEEP_REPORT=<file>` writes every block (field, value or sentence, rule ids and levels) as JSON; the output names each field, the sentence and the rules.
- **Log volume**: every request the API answers 429 and every probe write an audit line. A `ci` run writes about 870 lines, about 1.2 MB; an `all` run about 14,700 lines, 10 MB, plus 9 MB of access lines, two thirds of the proxy's 30 MB. Run `make logs-reset` after a full sweep.

## Audit log volume

The proxy logs to Docker's json-file driver, `max-size 10m`, `max-file 3`: at most 30 MB per container (see Logs and retention in [infrastructure.md](infrastructure.md)). Measured on 2026-11-23 with blocking on:

| Run | Audit lines | Bytes |
| --- | --- | --- |
| `make waf-check`, parts 1–4 | 11 (7 probes, 4 app 4xx: job search 422, vote 409, results 409, Grafana snapshot 403) | about 48 kB |
| `make waf-check`, part 5 (`waf-sweep.sh ci`, 2026-11-25) | 869 (127 probes, 736 API 429s on the corpus subset, a few app 4xx) | about 1.15 MB |
| `make grafana-check` | 7 (its intended 401s, 400s and the snapshot 403; Grafana Live 920320, no User-Agent, score 2) | about 4.5 kB (65 kB before INF-11, when every panel query matched) |
| `make files-check` | 6 (MinIO's intended 403s, one WAF block of the `text/html` upload) | about 5 kB |
| `make mail-check` | 1 (its intended unverified login, 403 JSON) | about 0.6 kB |
| `make https-check`, `images-check`, `metrics-check` | 0 | 0 |
| An open dashboard | 0 (was about 2.4 kB every 30 s) | 0 |

So about 25 `make waf-check` runs fill the 30 MB, before access lines (about 600 before part 5 was added). An attack scan fills it faster (1 to 12 kB per blocked request); the oldest file then rotates out, and `make logs-reset` empties it.

## Not covered

- WebSocket frames (above).
- Rate limiting and brute force: the API's limits per IP (`docs/api/api-contract.md`), not the WAF. ModSecurity's DoS rules are not enabled.
- Bot detection beyond scanner User-Agents (913100).
- Response bodies past 1 MB, uploaded file content past 13 MB (the API checks pictures with Pillow and videos by their header).
- Levels 3 and 4: not enabled.
- The CRS is pinned with the image (4.30.0); an update means rerunning `make waf-check` and `make grafana-check`.
