# ft\_transcendence — API Contract

Oct 27, 2026 · @byul-byul

The single source of truth between frontend and backend. It describes the reference API as it runs today (76 HTTP operations, 2 WebSockets) plus the changes the new backend will make; legacy `/chat/*` and draft-video routes are left out because we drop them.

## Conventions

JSON in, JSON out; JWT bearer auth; one error shape; cursor pagination.

| Topic | Rule |
| --- | --- |
| Base path | Reference: routes at the root (`/auth/login`). New backend: everything under `/api` behind Caddy (`https://<host>/api/auth/login`), WebSockets under `/ws` |
| Auth | `Authorization: Bearer <access_token>`; access token lives 15 min. A missing, invalid or expired token, or one made before a password change (`token_version`), gets 401 with `WWW-Authenticate: Bearer`. On 401 call `POST /auth/refresh` once, retry, else log out. Refresh before expiry to avoid 401s in the console |
| Error body | `{"error": {"code": "<http status as string>", "detail": <string or object>}}`. `detail` is an object only for the apply guard (`{"code", "next_step"}`). Validation errors: status 422, detail `"body → field: message"` (first error only). Unexpected errors: 500, detail `"Internal server error"` |
| Request id | Every response carries an `x-request-id` header (the caller's own value when it sends one, up to 64 characters); every server log line of that request has the same id |
| Rate limit | 429 with the same error body. Limits per IP: register 5/min, login 10/min, refresh 20/min, forgot 3/min, reset 5/min, change password 5/min |
| Pagination | Request `cursor` (id of the last item seen) + `limit`; response `{items: [...], next_cursor: id or null}`. Messages use `before_id` → `prev_before_id` (older pages) |
| Times | ISO 8601 with timezone, UTC (`2026-10-27T14:03:00+00:00`) |
| Ids | Integers |
| Money | `salary_amount` decimal as string or number, `salary_currency` ISO 4217 (3 capital letters) |
| Files | Never through the API: the API returns a presigned URL; the browser PUTs the file to it, then calls a `confirm` endpoint |

## Auth and users

Sign-up is two steps (register, then verify from the email); login returns a token pair.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/auth/register` | — | `{email, password}` password 8–128 | 202 `{message}`; the verification email is sent after the answer | 409 email already verified, 422, 429 |
| GET | `/auth/verify` | — | query `token` | 200 `{verified, email, updated}` | 400 invalid, expired, or replaced by a newer link |
| POST | `/auth/login` | — | `{email, password}` | 200 `{access_token, refresh_token, token_type}` | 401 wrong credentials (same answer for an unknown email), 403 email not verified, 429 |
| POST | `/auth/refresh` | — | `{refresh_token}` | 200 new pair (old refresh revoked) | 401 invalid, reused, expired, or password changed; 429 |
| POST | `/auth/logout` | — | `{refresh_token}` (optional) | 204 always, even with no token or a bad one | — |
| POST | `/auth/change-password` | Bearer | `{current_password, new_password}` | 204; all tokens revoked | 400 `wrong_current_password` |
| POST | `/auth/forgot-password` | — | `{email}` | 202 always | — |
| POST | `/auth/reset-password` | — | `{token, new_password}` | 204; all tokens revoked | 400 invalid / expired |
| GET | `/users/me` | Bearer | — | 200 `UserOut` | 401 |
| PATCH | `/users/me` | Bearer | any subset of `{first_name, last_name, position, birth_date, bio}`; age ≥ 18 | 200 `UserOut` | 401, 422 |
| DELETE | `/users/me` | Bearer | — | 204 (soft delete) | 401 |

`UserOut` = `{id, email, first_name, last_name, position, birth_date, bio, avatar_object_key, is_email_verified}` (new backend, BE-05; `avatar_url` comes with BE-08). The reference also sends `phone`, `username`, `is_phone_verified` and `account_number` (`WZ-000123`); the new backend drops them.

Sign-up and login in the new backend (BE-03):

- Emails are compared in lower case. Registering again before the email is verified keeps the one account, replaces its password with the new one, raises `users.token_version` and sends a new link (202). That is also how a new link is asked for.
- The verification email links to the frontend page `<FRONTEND_BASE_URL>/verify-email?token=…` (valid 24 h); that page calls `GET /api/auth/verify?token=…`. The link carries `ver` (`users.token_version`), so **only the newest link is valid**: it verifies the account with the newest password, and every older link answers 400. Opening the newest link twice answers 200 with `updated: false`. A link and a sign-up arriving together are handled one after the other by the database, so a sign-up never changes an account that has just been verified (that sign-up gets 409).
- Access token: JWT (HS256), 15 min, claims `sub` (user id), `scope` (`access`), `ver` (`users.token_version`), `jti`, `iat`, `exp`. Refresh token: JWT, 30 days, stored by its `jti` in `refresh_tokens`; each refresh revokes it and returns a new pair (rotation), and a reused one gets 401.
- A deleted account gets the same 401 as a wrong password at login, and 401 on every protected route.

The profile in the new backend (BE-05):

- `PATCH /users/me` changes only the fields that are sent: a field left out keeps its value, and `{}` changes nothing (200). `first_name` and `last_name` 1–50 characters, `position` 1–100, `bio` up to 500; spaces around them are removed. `birth_date` is `YYYY-MM-DD`, and the user must be at least 18 full years old today, else 422 `"body → birth_date: You must be at least 18 years old"`. Only `bio` accepts `null` (it empties the bio). Any other field (`email`, `status`, `phone`, …) gets 422 `"body → <field>: Extra inputs are not permitted"`, and then nothing is changed. No body at all gets 422.
- `DELETE /users/me` sets `users.status` to `deleted`; the row and the profile stay. From then on the user's access and refresh tokens get 401, login gets the same 401 as a wrong password, and the email stays taken (register answers 409).

## Friends, profiles and conversations

Friendship is one row per pair; conversations are the only chat. New messages also arrive over the WebSocket, so REST is for history and sending.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/friends/requests` | Bearer | `{addressee_id}` | 201 `FriendshipOut` | 400 self, 404 user, 409 pending / already friends |
| GET | `/friends/requests` | Bearer | — | 200 incoming pending `FriendshipOut[]` | — |
| POST | `/friends/requests/{id}/accept` | Bearer | — | 200 `FriendshipOut` | 403 not addressee, 409 not pending |
| POST | `/friends/requests/{id}/decline` | Bearer | — | 200 `FriendshipOut` | same |
| DELETE | `/friends/{id}` | Bearer | — | 204 | 403, 404 |
| GET | `/friends` | Bearer | — | 200 `[{user_id, first_name, last_name, position, avatar_object_key, is_online}]` | — |
| GET | `/users/{id}/profile` | Bearer | — | 200 `{id, first_name, last_name, position, bio, avatar_object_key, is_online, friendship_status}` | 404 |
| POST | `/conversations` | Bearer | `{type: "direct", peer_user_id, job_id?}` | 201 `ConversationOut` (existing one if the pair already has a chat) | 400 no peer, 403 job not yours |
| GET | `/conversations` | Bearer | query `limit` ≤ 100 | 200 `ConversationOut[]`, newest first | — |
| GET | `/conversations/unread` | Bearer | — | 200 `{total_unread}` | — |
| GET | `/conversations/{id}` | Bearer | — | 200 `ConversationOut` | 404 |
| DELETE | `/conversations/{id}/leave` | Bearer | — | 204 | 403, 404 |
| GET | `/conversations/{id}/participants` | Bearer | — | 200 `[{user_id, role, joined_at, last_read_message_id, is_muted}]` | 403, 404 |
| POST | `/conversations/{id}/participants` | Bearer (admin) | `{user_id, role}` | 201 `{added: true}` | 403 |
| DELETE | `/conversations/{id}/participants/{uid}` | Bearer | — | 204 | 403 |
| GET | `/conversations/{id}/messages` | Bearer | query `before_id`, `limit` | 200 `{items: MessageOut[] oldest→newest, prev_before_id}` | 403, 404 |
| POST | `/conversations/{id}/messages` | Bearer | `{content 1–4000, reply_to_id?, idempotency_key? ≤ 64}` | 200 `{items: [MessageOut]}` + WS push | 403, 404 |
| PATCH | `/conversations/{id}/messages/{mid}` | Bearer | `{content}` | 200 `MessageOut` | 403 not yours, 409 after 15 min |
| DELETE | `/conversations/{id}/messages/{mid}` | Bearer | — | 204 (soft) | 403 not yours |
| POST | `/conversations/{id}/read` | Bearer | `{last_message_id}` | 204 + WS `conversation_updated` | 403 |

- `friendship_status`: `null`, `pending_sent`, `pending_received`, `accepted`.
- `ConversationOut` = `{id, type, title, job_id, job_title, last_message_id, last_message_content, last_message_author_id, unread_count, updated_at}`.
- `MessageOut` = `{id, conversation_id, author_id, content, status (sent / delivered / read), message_type, reply_to_id, idempotency_key, edited_at, deleted_at, created_at}`.

## Companies, jobs and applications

An employer is a user who owns an active company; jobs belong to the company. A job is visible to everyone only in status `open`.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/companies` | Bearer | `{name, description?, country?, city?, district?}` | 201 `CompanyOut` | 409 already has one |
| GET | `/companies/me` | Bearer | — | 200 `CompanyOut` | 404 none (to change: 200 `null`) |
| PATCH | `/companies/me` | Bearer | `{name, country, city, district?, country_code?}` | 200 `CompanyOut` | 404, 422 |
| DELETE | `/companies` | Bearer | — | 204 (soft, idempotent) | — |
| POST | `/jobs` | Bearer (employer) | `JobCreate` | 201 `JobOut` | 404 no company, 422 |
| PATCH | `/jobs/{id}` | Bearer (owner) | any `JobCreate` fields | 200 `JobOut` | 404 |
| DELETE | `/jobs/{id}` | Bearer (owner) | — | 204 (soft) | 404 |
| GET | `/jobs/mine` | Bearer (employer) | — | 200 `JobOut[]` with `views_count`, `applications_count`, `new_applications_count` | 404 no company |
| GET | `/jobs/open` | — | query below | 200 `{items: JobOut[], next_cursor}` | 422 |
| GET | `/jobs/{id}` | optional | — | 200 `JobOut` (non-open only for the owner) | 404 |
| POST | `/jobs/{id}/view` | optional | — | 204 (counted once per user per 24 h) | — |
| POST | `/jobs/{id}/apply` | Bearer | `{cover_note? ≤ 1000}` | 201 `ApplicationOut` | 422 `{code: profile_incomplete or no_video, next_step}`, 403 own job, 404, 409 duplicate |
| GET | `/applications/mine` | Bearer | query `status`, `cursor`, `limit` | 200 `{items, next_cursor}` | — |
| GET | `/applications/{id}` | Bearer (applicant or job owner) | — | 200 `ApplicationOut` | 403, 404 |
| DELETE | `/applications/{id}` | Bearer (applicant) | — | 204 → `withdrawn` | 404, 409 |
| GET | `/jobs/{id}/applications` | Bearer (job owner) | query `status`, `cursor`, `limit` | 200 `{items, next_cursor}` | 403, 404 |
| PATCH | `/applications/{id}/status` | Bearer (job owner) | `{status, note? ≤ 500}` | 200 `ApplicationOut` | 403, 409 transition not allowed |

**`GET /jobs/open` query:** `lat`, `lng`, `radius_km` (≤ 500; all three for radius), `schedule` (`full_time`, `part_time`, `internship`), `salary_min`, `salary_max`, `urgency` (`normal`, `urgent`, `hot`), `keyword` (full-text), `position` (title contains), `sort_by` (`newest` default, `nearest` needs lat/lng), `cursor`, `limit` 1–100 (default 20).

- `JobCreate` = `{title 1–200, description, latitude, longitude, location ≤ 150, status (active or open, default active), salary_amount?, salary_type (hourly, daily, weekly, monthly), salary_currency?, schedule, urgency}`.
- `JobOut` = `JobCreate` fields + `{id, owner_id, company_name, views_count, applications_count, new_applications_count, created_by_id, updated_by_id, created_at, updated_at}`.
- `ApplicationOut` = `{id, job_id, applicant_id, company_id, intro_video_id, status, cover_note, conversation_id, applied_at, updated_at, viewed_at}`.
- `CompanyOut` = `{id, owner_user_id, name, description, logo_object_key, status, country, city, district, country_code, created_at, updated_at}`.

## Media

Every upload is three steps: ask for a URL, PUT the file to it from the browser, confirm. Signed URLs expire (default 5 min for viewing, 15 min for uploading), so never cache them.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/media/intro-video/upload-url` | Bearer | `{content_type: "video/mp4", ext: "mp4", expires_sec 60–3600}` | 200 `{object_key, put_url, get_url, expires_sec, max_bytes}` | 415 not mp4 |
| POST | `/media/intro-video/confirm` | Bearer | `{object_key, duration_sec 1–30, size_bytes ≤ 52428800, content_type: "video/mp4"}` | 201 `{id, moderation_status: pending, lifecycle_status: loaded}` | 400 key not yours, 409 3 videos already / duplicate |
| GET | `/media/intro-video/mine` | Bearer | query `expires_sec` | 200 `{items: [{id, object_key, duration_sec, size_bytes, content_type, moderation_status, lifecycle_status, created_at, updated_at, signed_url, expires_sec}]}` | — |
| POST | `/media/intro-video/{id}/post` | Bearer | — | 200 `{id, moderation_status, lifecycle_status}`; previous posted video becomes `unposted` | 409 not approved |
| POST | `/media/intro-video/{id}/unpost` | Bearer | — | 200 same shape | 409 not posted |
| POST | `/media/intro-video/{id}/delete` | Bearer | — | 200 same shape (soft delete) | 404 |
| GET | `/media/feed` | Bearer | query `limit` ≤ 50, `cursor`, `expires_sec`, `job_id?` | 200 `{items: [{id, user_id, duration_sec, size_bytes, content_type, signed_url, expires_sec, created_at, author_name, author_position}], next_cursor}` | — |
| POST | `/media/avatar/upload-url` | Bearer | query `ext` (default jpg), `expires_sec` | 200 `{object_key, put_url, expires_sec}` | — |
| POST | `/media/avatar/confirm` | Bearer | `{object_key}` | 204 | — |
| POST | `/media/company-logo/upload-url` | Bearer (employer) | query `ext`, `expires_sec` | 200 `{object_key, put_url, expires_sec}` | 404 no company |
| POST | `/media/company-logo/confirm` | Bearer (employer) | `{object_key}` | 204 | 404 |

- Statuses: moderation `pending → approved | rejected` (+ `moderation_error` once fixed); lifecycle `loaded → posted ⇄ unposted`, any → `deleted`. Poll `/media/intro-video/mine` while a video is `pending` (or listen for a WS event once added).
- The browser PUT to `put_url` is a plain PUT of the file bytes to `https://<host>/files/<object_key>?X-Amz-…`. That is the frontend's own origin, so no CORS is involved (INF-04, Infrastructure doc). Use XHR or fetch with upload progress for the progress bar.
- With `job_id`, the employer feed lists that job's applicants first, then candidates whose position matches the job title, then everyone else.
- Avatar and logo are returned only as `avatar_object_key` / `logo_object_key` today; the frontend cannot turn a key into a URL. See planned changes.

## Game

Join the queue over REST, then wait for `game_room_formed` on `/ws`, open `/game/ws` for the room chat, vote over REST, fetch results when the room finishes.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/game/queue/join` | Bearer | — | 202 `{message: "queued"}` | — |
| DELETE | `/game/queue/leave` | Bearer | — | 204 | — |
| GET | `/game/rooms/{id}` | Bearer (participant) | — | 200 `{id, state, target_size, participants: [{id, display_label}]}` | 403, 404 |
| POST | `/game/rooms/{id}/votes` | Bearer (participant) | `{target_participant_id, guess: "bot" or "human"}` | 201 `{message}` | 400 self, 409 not voting phase / already voted, 422 |
| GET | `/game/rooms/{id}/results` | Bearer (participant) | — | 200 `{room_id, state, participants: [{participant_id, display_label, is_bot, score (humans), deception_rate (bots)}]}` | 409 not finished |

Room states: `waiting → discussion (120 s) → voting (45 s) → finished`. The server moves the phases; today the phase events carry only the room id, so the client cannot show an exact countdown (planned change: send phase\_ends\_at).

## System

Health and spec endpoints of the new backend (BE-01). Routes under `/_internal/*` are not part of this contract: they are left out of the spec, need the `X-Internal-Key` header and are blocked by the proxy.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/health` | — | — | 200 `{status: "ok"}` | — |
| GET | `/api/openapi.json` | — | — | 200 OpenAPI 3.1 spec of every public route | — |
| GET | `/api/docs` | — | — | 200 Swagger UI, only when `ENV=dev` | 404 otherwise |
| GET | `/api/docs/oauth2-redirect` | — | — | 200 Swagger UI's OAuth helper page, only when `ENV=dev` | 404 otherwise |

## WebSocket protocol

One socket per tab on `/ws`; every frame is JSON `{type, payload}`. Delivery is per user, not per socket: an event for a user reaches every socket that user has open, including `/game/ws`, so the client must route by `type` and ignore what it does not know.

**Connect:** `wss://<host>/ws?token=<access_token>` (reference). Bad token, unknown or deleted user, or old `token_version` → closed with code 1008. Game room socket: `wss://<host>/game/ws?token=<access_token>&room_id=<id>`, closed 1008 if not a participant.

| Direction | `type` | Payload | When |
| --- | --- | --- | --- |
| client → server | `ping` | — | Keep-alive; send every 25–30 s |
| client → server | `delivered` | `{message_id}` at top level | Message shown on this device |
| client → server | `read` | `{conversation_id, last_message_id}` at top level | Conversation opened / scrolled to bottom |
| client → server (`/game/ws`) | `chat_message` | `{text}` at top level | Player sends a room message during discussion |
| server → client | `pong` | — | Reply to ping |
| server → client | `message` | `MessageOut` | New message in any of my conversations (mine too) |
| server → client | `message_status` | `{message_id, status: "delivered"}` | A participant marked it delivered |
| server → client | `conversation_updated` | `{conversation_id, unread_count}` (`null` for the other side) | Someone read a conversation |
| server → client | `game_room_formed` | `{room_id}` | Matchmaking put me in a room |
| server → client | `game_message` | `{id, participant_id, display_label, text}` | Room message from a player or a bot |
| server → client | `game_phase_voting` | `{room_id}` | Discussion ended |
| server → client | `game_phase_finished` | `{room_id}` | Voting ended, results ready |

**Client rules:** reconnect with backoff (1 s, 2 s, 5 s, then every 10 s) and after reconnecting reload what you show (conversation list, open messages, room state), because events sent while offline are lost. Refresh the access token before reconnecting.

## Planned changes for the new backend

The frontend should code against these from day one; the backend Tech Lead confirms each one before it lands and ticks it here.

| Done | Change | Why |
| --- | --- | --- |
| \[ \] | All routes under `/api`, WebSockets under `/ws` and `/ws/game` on the same origin | One origin through Caddy: no CORS, no mixed content |
| \[ \] | `GET /companies/me` → 200 `null` when the user has no company | No 404 in the Chrome console |
| \[ \] | `UserOut`, public profile, friends list return `avatar_url` (signed or public path) with a default avatar; same for `logo_url` | Frontend cannot show images from object keys |
| \[x\] | `PATCH /users/me` accepts partial updates | Edit one field without resending the whole profile |
| \[x\] | Drop `phone`, `is_phone_verified`, `username`, `account_number` from `UserOut` unless a feature uses them | Smaller contract, no dead fields |
| \[ \] | Email links open frontend routes `/verify-email?token=` and `/reset-password?token=`, which call the API | Links currently show raw JSON or 405 |
| \[ \] | WebSocket auth with a one-time ticket: `POST /api/ws/ticket` → `{ticket}` valid 30 s, then `wss://<host>/ws?ticket=` | Access tokens no longer in URLs and logs |
| \[ \] | New events `message_updated`, `message_deleted`, `presence` `{user_id, is_online}`, `video_moderated` `{id, moderation_status}` | Live edits, online dots, no polling for moderation |
| \[ \] | Game: `GET /api/game/rooms/{id}/messages`; room payload and phase events include `phase_ends_at`; results include `winner_participant_ids` | Reconnect, countdown, clear win / loss |
| \[ \] | Game: minimum room size 3; votes must target the same room | Multiplayer 3+ module; integrity |
| \[ \] | Game results add `winner_participant_ids` (ids of the participants with outcome `win`; empty on a draw), `is_draw` (boolean: the top score is shared, or the single human scored 0) and per participant `outcome` (`win`, `draw` or `loss` for humans; `null` for bots). Rules: [game/turing-duel-rules.md](../game/turing-duel-rules.md) | Clear win / draw / loss result (DOC-08, BE-10) |
| \[ \] | Jobs: `active` renamed `draft`; only `open` jobs accept applications or chats | One clear meaning per status |
| \[ \] | Remove `/chat/*`, `/media/intro-video/draft/*`, `/media/feed/demo`, `/media/health` (moved to `/_internal`) | Legacy and leaks |
| \[ \] | OAuth: `GET /api/auth/oauth/42/start` → redirect; `GET /api/auth/oauth/42/callback` → token pair | OAuth module (tier B) |
| \[ \] | `GET /metrics` for Prometheus, internal only | Monitoring module |

## Machine-readable spec

The reference spec is exported as `wozu-reference-openapi.json` (OpenAPI 3.1, 62 paths, shared alongside this doc); WebSockets are not in it, see the protocol above.

- **Reference:** the spec is served at `/_internal/openapi.json` and Swagger at `/_internal/docs`, both behind the `X-Internal-Key` header. To regenerate without a running stack: `python -c "import json; from app.main_ft import app; print(json.dumps(app.openapi()))"` with the env vars from `.env.example`.
- **New backend:** serve Swagger at `/api/docs` in development; the frontend generates TypeScript types from `/api/openapi.json` with `openapi-typescript`, so a contract change shows up as a compile error, not a runtime bug.
- **Rule:** a PR that changes the API updates this doc in the same card.
