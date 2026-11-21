# ft\_transcendence — API Contract

Oct 27, 2026 · @byul-byul

The single source of truth between frontend and backend. It describes the reference API as it runs today (76 HTTP operations, 2 WebSockets) plus the changes the new backend will make; legacy `/chat/*` and draft-video routes are left out because we drop them.

## Conventions

JSON in, JSON out; JWT bearer auth; one error shape; cursor pagination.

| Topic | Rule |
| --- | --- |
| Base path | Reference: routes at the root (`/auth/login`). New backend: everything under `/api` behind the nginx + ModSecurity front proxy (`https://<host>/api/auth/login`), WebSockets under `/ws` |
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
| POST | `/auth/change-password` | Bearer | `{current_password, new_password}` new password 8–128 | 204; all tokens revoked | 400 wrong current password, 401, 422, 429 |
| POST | `/auth/forgot-password` | — | `{email}` | 202 `{message}` always, whether the email has an account or not | 422 not an email, 429 |
| POST | `/auth/reset-password` | — | `{token, new_password}` new password 8–128 | 204; all tokens revoked | 400 invalid, expired or already used link; 422, 429 |
| GET | `/users/me` | Bearer | — | 200 `UserOut` | 401 |
| PATCH | `/users/me` | Bearer | any subset of `{first_name, last_name, position, birth_date, bio}`; age ≥ 18 | 200 `UserOut` | 401, 422 |
| DELETE | `/users/me` | Bearer | — | 204 (soft delete; the user's company is soft-deleted too) | 401 |

`UserOut` = `{id, email, first_name, last_name, position, birth_date, bio, avatar_object_key, avatar_url, is_email_verified}` (new backend, BE-05; `avatar_url` from BE-08: my picture's public address, or the default picture, see Media). The reference also sends `phone`, `username`, `is_phone_verified` and `account_number` (`WZ-000123`); the new backend drops them.

Sign-up and login in the new backend (BE-03):

- Emails are compared in lower case. Registering again before the email is verified keeps the one account, replaces its password with the new one, raises `users.token_version` and sends a new link (202). That is also how a new link is asked for.
- The verification email links to the frontend page `<FRONTEND_BASE_URL>/verify-email?token=…` (valid 24 h); that page calls `GET /api/auth/verify?token=…`. The link carries `ver` (`users.token_version`), so **only the newest link is valid**: it verifies the account with the newest password, and every older link answers 400. Opening the newest link twice answers 200 with `updated: false`. A link and a sign-up arriving together are handled one after the other by the database, so a sign-up never changes an account that has just been verified (that sign-up gets 409).
- Access token: JWT (HS256), 15 min, claims `sub` (user id), `scope` (`access`), `ver` (`users.token_version`), `jti`, `iat`, `exp`. Refresh token: JWT, 30 days, stored by its `jti` in `refresh_tokens`; each refresh revokes it and returns a new pair (rotation), and a reused one gets 401.
- A deleted account gets the same 401 as a wrong password at login, and 401 on every protected route.

Passwords in the new backend (BE-04):

- `POST /auth/change-password` needs the right current password, else 400 `"Wrong current password"` (400, not 401, so the client does not refresh and log out). The new password follows the sign-up rule (8–128). On success `users.token_version` goes up by 1: from then on every access and refresh token of the user gets 401, the one that made the request too, so the frontend sends the user to log in again.
- `POST /auth/forgot-password` answers the same 202 `{"message": "If this email has an account, a reset link is on its way"}` for any well-formed email (no account enumeration). Only an active account with a verified email gets the email, which links to the frontend page `<FRONTEND_BASE_URL>/reset-password?token=…`. The token is 64 random URL-safe characters, valid 1 h, single use; the database keeps only its SHA-256 (`password_reset_tokens.token`).
- `POST /auth/reset-password` is called by that page with `{token, new_password}`. 204: the password is replaced and `token_version` goes up, as for a change. A wrong, expired or already used token gets 400 `"Invalid or expired link"`; a 422 (a bad new password) does not use up the link.
- After a change or a reset, every other reset link of the user that still works is closed too: all of the user's tokens (access, refresh, reset) stop working together.
- Both emails (verify and reset) go through one sender: SMTP to Mailpit by default (`SMTP_HOST`, `SMTP_PORT`, `MAIL_FROM`), Brevo's API only when `BREVO_API_KEY` is set.

The profile in the new backend (BE-05):

- `PATCH /users/me` changes only the fields that are sent: a field left out keeps its value, and `{}` changes nothing (200). `first_name` and `last_name` 1–50 characters, `position` 1–100, `bio` up to 500; spaces around them are removed. `birth_date` is `YYYY-MM-DD`, and the user must be at least 18 full years old today, else 422 `"body → birth_date: You must be at least 18 years old"`. Only `bio` accepts `null` (it empties the bio). Any other field (`email`, `status`, `phone`, …) gets 422 `"body → <field>: Extra inputs are not permitted"`, and then nothing is changed. No body at all gets 422.
- `DELETE /users/me` sets `users.status` to `deleted`; the row and the profile stay. From then on the user's access and refresh tokens get 401, login gets the same 401 as a wrong password, and the email stays taken (register answers 409). The files of the avatar and of the user's company logo are deleted from storage at once and both keys are emptied (BE-08), because their public addresses would otherwise keep working. The user's active company, if any, is soft-deleted in the same transaction (`companies.status` becomes `deleted`), so it and its jobs leave every public view: `GET /jobs/{id}` answers 404 and `GET /jobs/open` leaves them out. The jobs and the applications already sent stay as they are.

## Friends, profiles and conversations

Friendship is one row per pair; conversations are the only chat. New messages also arrive over the WebSocket, so REST is for history and sending.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/friends/requests` | Bearer | `{addressee_id}` | 201 `FriendshipOut` | 400 self, 404 user, 409 pending / already friends |
| GET | `/friends/requests` | Bearer | — | 200 incoming pending `FriendshipOut[]` | — |
| POST | `/friends/requests/{id}/accept` | Bearer | — | 200 `FriendshipOut` | 403 not addressee, 404, 409 not pending |
| POST | `/friends/requests/{id}/decline` | Bearer | — | 200 `FriendshipOut` | 403 not addressee, 404, 409 not pending |
| DELETE | `/friends/{id}` | Bearer | — | 204 | 403, 404 |
| GET | `/friends` | Bearer | — | 200 `[{friendship_id, user_id, first_name, last_name, position, avatar_object_key, avatar_url, is_online}]` | — |
| GET | `/users/{id}/profile` | Bearer | — | 200 `{id, first_name, last_name, position, bio, avatar_object_key, avatar_url, is_online, friendship_status, friendship_id}` | 404 |
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
| PATCH | `/conversations/{id}/messages/{mid}` | Bearer | `{content}` | 200 `MessageOut` + WS `message_updated` | 403 not yours, 404, 409 after 15 min |
| DELETE | `/conversations/{id}/messages/{mid}` | Bearer | — | 204 (soft) + WS `message_deleted` | 403 not yours, 404 |
| POST | `/conversations/{id}/read` | Bearer | `{last_message_id}` | 204 + WS `conversation_updated` | 403, 404 |

- `friendship_status`: `null`, `pending_sent`, `pending_received`, `accepted`; `friendship_id`: `int | null` pointing to the friendship row when a relationship exists.
- `ConversationOut` = `{id, type, title, job_id, job_title, last_message_id, last_message_content, last_message_author_id, unread_count, updated_at, peer}`. For direct conversations (`type: "direct"`), `peer` is `{id, first_name, last_name, display_name, avatar_url}` representing the other participant; `peer` is `null` for non-direct chats.
- `MessageOut` = `{id, conversation_id, author_id, content, status (sent / delivered / read), message_type, reply_to_id, idempotency_key, edited_at, deleted_at, created_at}`.

## Companies, jobs and applications

An employer is a user who owns an active company; jobs belong to the company. A job is visible to everyone only in status `open`.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/companies` | Bearer | `{name, description?, country?, city?, district?}` | 201 `CompanyOut` | 409 already has one |
| GET | `/companies/me` | Bearer | — | 200 `CompanyOut` or `null` | — |
| PATCH | `/companies/me` | Bearer | `{name, country, city, district?, country_code?}` | 200 `CompanyOut` | 404, 422 |
| DELETE | `/companies` | Bearer | — | 204 (soft, idempotent; the logo file is deleted, BE-08) | — |
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

- `JobCreate` = `{title 1–200, description, latitude, longitude, location ≤ 150, status (draft or open, default draft), salary_amount?, salary_type (hourly, daily, weekly, monthly), salary_currency?, schedule, urgency}`.
- `JobOut` = `JobCreate` fields + `{id, owner_id, company_name, views_count, applications_count, new_applications_count, created_by_id, updated_by_id, created_at, updated_at}`.
- `ApplicationOut` = `{id, job_id, applicant_id, company_id, intro_video_id, status, cover_note, conversation_id, applied_at, updated_at, viewed_at}`.
- `CompanyOut` = `{id, owner_user_id, name, description, logo_object_key, logo_url, status, country, city, district, country_code, created_at, updated_at}`. `logo_url` (new backend, BE-08): the logo's public address, or `null` without a logo (see Media).

## Media

Every upload is three steps: ask for a URL, PUT the file to it from the browser, confirm. Signed URLs expire (default 5 min for viewing, 15 min for uploading), so never cache them.

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/media/intro-video/upload-url` | Bearer | `{content_type: "video/mp4", ext: "mp4", expires_sec 60–3600}` | 200 `{object_key, put_url, get_url, expires_sec, max_bytes}` | 415 not mp4 (`content_type` or `ext`), 422 `expires_sec` |
| POST | `/media/intro-video/confirm` | Bearer | `{object_key, duration_sec 1–30, size_bytes ≤ 52428800, content_type: "video/mp4"}` | 201 `{id, moderation_status: pending, lifecycle_status: loaded}` | 400 key not yours or no file uploaded there, 409 3 videos already / already confirmed, 413 the stored file is over 50 MiB, 415 the stored file is not an MP4, 422 |
| GET | `/media/intro-video/mine` | Bearer | query `expires_sec` | 200 `{items: [{id, object_key, duration_sec, size_bytes, content_type, moderation_status, lifecycle_status, created_at, updated_at, signed_url, expires_sec}]}`, not the deleted ones, newest first | 422 `expires_sec` |
| POST | `/media/intro-video/{id}/post` | Bearer | — | 200 `{id, moderation_status, lifecycle_status}`; previous posted video becomes `unposted` | 404 not mine / deleted, 409 not approved / already posted, 422 `id` under 1 or too large |
| POST | `/media/intro-video/{id}/unpost` | Bearer | — | 200 same shape | 404, 409 not posted, 422 `id` under 1 or too large |
| POST | `/media/intro-video/{id}/delete` | Bearer | — | 200 same shape (soft delete) | 404 not mine / already deleted, 422 `id` under 1 or too large |
| GET | `/media/feed` | Bearer | query `limit` ≤ 50, `cursor`, `expires_sec`, `job_id?` | 200 `{items: [{id, user_id, duration_sec, size_bytes, content_type, signed_url, expires_sec, created_at, author_name, author_position}], next_cursor}` | 422 `limit` 1–50, `expires_sec`, `cursor` that is no video's id, `job_id` under 1 or too large |
| POST | `/media/avatar/upload-url` | Bearer | query `ext` (`jpg` default, `png`, `webp`), `expires_sec` 60–3600 (default 900) | 200 `{object_key, put_url, expires_sec, max_bytes}`, `object_key` in the private `staging/` folder | 415 other extension, 422 `expires_sec` |
| POST | `/media/avatar/confirm` | Bearer | `{object_key}` | 204; `GET /users/me` then gives the new `avatar_url` | 400 key not yours, no file uploaded there or already confirmed, 413 the stored file is over 5 MiB or the picture over 25 million pixels, 415 extension, or the file is not a real jpg / png / webp picture, 422 |
| GET | `/media/avatar/default.svg` | — | — | 200 `image/svg+xml`, the default avatar picture | — |
| POST | `/media/company-logo/upload-url` | Bearer (employer) | same query as the avatar | 200 same shape | 404 no company, 415, 422 |
| POST | `/media/company-logo/confirm` | Bearer (employer) | `{object_key}` | 204; `GET /companies/me` then gives the new `logo_url` | 404 no company, 400, 413, 415, 422 |

- Statuses: moderation `pending → approved | rejected` (+ `moderation_error` once fixed); lifecycle `loaded → posted ⇄ unposted`, any → `deleted`. Poll `/media/intro-video/mine` while a video is `pending` (or listen for a WS event once added).
- The browser PUT to `put_url` is a plain PUT of the file bytes to `https://<host>/files/<object_key>?X-Amz-…`. That is the frontend's own origin, so no CORS is involved (INF-04, Infrastructure doc). Use XHR or fetch with upload progress for the progress bar.
- With `job_id`, the employer feed lists that job's applicants first, then candidates whose position matches the job title, then everyone else.
- Avatar and logo: the reference returns only `avatar_object_key` / `logo_object_key`, which the frontend cannot turn into a URL; the new backend returns `avatar_url` (BE-08, below).

Intro videos in the new backend (BE-07); every route needs the access token (401 otherwise):

- `upload-url` makes the key `users/<my id>/intro/<uuid>.mp4` and signs both links for `MINIO_EXTERNAL_ENDPOINT` (`https://localhost/files/<key>?X-Amz-…`), both valid `expires_sec` (15 min by default); the links of `mine` and the feed are valid 5 min by default (`expires_sec` is 60–3600 everywhere). The bucket is private (only `avatars/` and `logos/` can be downloaded without a signature, BE-08): without a valid signature MinIO answers 403. `get_url` shows the upload only until `confirm`, which deletes it (404 after); `mine` then gives the video's link. The drafts, the demo feed and `/media/health` are not ported (404).
- `confirm` keeps a copy of the upload and checks that copy, not what the browser says: the key must have exactly that shape with my own id (400; a `videos/` key is refused too). MinIO then copies the upload to a new key that no upload link ever pointed at, `videos/<my id>/<new uuid>.mp4`, stored with Content-Type `video/mp4`, and the upload is deleted, accepted or refused (400 "No uploaded file at this object_key" when there was none). The copy's real size must be at most 50 MiB (413; the saved `size_bytes` is the real one) and its first 8 bytes an MP4 file header, `ftyp` at bytes 4–7 (415); a refused copy is deleted too. The video's `object_key` (in `mine` and the moderation task) is the copy's key. So `put_url`, valid until it expires, can only write at the upload key again, which nothing reads after `confirm`: it can never change a confirmed video. `duration_sec` is what the browser reports (1–30, else 422): the API does not open the video, so the moderation worker (BE-29) measures the real duration (ffprobe) and rejects a video over 30 s. At most 3 videos that are not deleted (409). A key confirmed once cannot be confirmed again, even after a delete: its upload is gone (400). A video confirmed before `confirm` made copies kept its upload key as `object_key`; confirming that key again is 409 "This video is already confirmed", and nothing is copied or deleted.
- After answering, `confirm` puts one Celery task on the Redis queue `celery`: `app.worker.tasks.moderation.run_moderation_task` with the arguments `[video_id, object_key]` (the copy's key), for the worker (`celery -A app.worker.celery_app worker`, BE-29). If Redis cannot be reached, `confirm` still answers 201 and the video stays `pending`; the error is logged, and the worker's check for stuck pending videos (BE-29) queues it again.
- `post`: only an `approved` video that is not posted yet (409); my previously posted video becomes `unposted` (one posted video per user, also a unique index in the database). `unpost`: only a posted video (409). `delete` sets `lifecycle_status = deleted`; the row and the file stay. A deleted video is gone for its owner: not in `mine` or the feed, `post` / `unpost` / `delete` answer 404, and it no longer counts in the 3. Someone else's video gets the same 404 as a missing one.
- The feed shows approved, posted videos of active accounts, newest first. An employer (a user with an active company) sees only `video_rating` A and B. With `job_id`, three groups, newest first in each: 1. that job's applicants still `submitted` or `viewed`, 2. users whose position contains the job title (any case), 3. everyone else; an unknown job gives the plain order. `cursor` is the `next_cursor` of the page before (the id of its last video; pages keep the group order); `next_cursor` is `null` on the last page. `limit` 1–50, default 20.
- A `cursor` that is no video's id gets 422 `"query → cursor: No video has this id: use the next_cursor of the page before"` (with or without `job_id`); a cursor under 1, too large for an id, or not a whole number gets the usual 422 of a bad query field (`"query → cursor: …"`). A `next_cursor` the API gave keeps working even if its video has left the feed since (unposted or deleted): the next page still comes.
- An id in the address (the video `{id}` of `post`, `unpost` and `delete`, the feed's `job_id`) must be a whole number from 1 to 9223372036854775807, the largest id the database holds (BIGINT); anything else gets the usual 422 (`"path → video_id: …"`, `"query → job_id: …"`) before the database is asked. A valid id that matches nothing is still 404 for a video and the plain order for a job.

Avatars and company logos in the new backend (BE-08):

- **Read path, agreed with infra (INF-04):** the bucket stays private, but anyone may download (not list, not upload) the files under `avatars/` and `logos/`. So `avatar_url` is a plain address with no signature, `<MINIO_EXTERNAL_ENDPOINT>/<bucket>/<key>`, e.g. `https://localhost/files/avatars/12/<uuid>.png`. It never expires: a page left open never shows a broken picture, and the browser can cache it. Signed links (`?X-Amz-…`) are only for private files: the intro videos.
- **Upload into `staging/`, then the API publishes:** the browser never writes into `avatars/` or `logos/`. `upload-url` gives a key in the private folder `staging/`, `staging/avatars/<user id>/<uuid>.<ext>` or `staging/logos/<company id>/<uuid>.<ext>` (a logo belongs to the company, so its folder does too), and a `put_url` signed for that key only; nobody can download from `staging/` (403). `confirm` checks the upload and, if it is good, the API itself writes a copy of it at a new key that no upload link ever pointed at, `avatars/<user id>/<new uuid>.<ext>` or `logos/<company id>/<new uuid>.<ext>`, which goes into `users.avatar_object_key` (or `companies.logo_object_key`); `avatar_url` / `logo_url` point at it. The upload itself is deleted, accepted or refused. So nothing unchecked is ever public, and the upload link, valid until it expires, can only write into `staging/` again, never change a published picture.
- `ext` is `jpg`, `png` or `webp`, in any case (the key is written in small letters); anything else gets 415. The `Content-Type` of the PUT does not matter: the public copy gets `image/jpeg`, `image/png` or `image/webp` from the API, after the check.
- `confirm` checks the file in storage, not what the browser says: the extension is jpg, png or webp (415); the key has exactly that `staging/` shape with my own id, or my company's id (400; a key under `avatars/` or `logos/` is refused too); `stat_object` finds a file there (400 "No uploaded file at this object_key: …", also for an upload already confirmed), of at most 5 MiB = 5 242 880 bytes (413; neither the reference nor this contract had a limit). The API then reads it once, and the image library Pillow opens it as the type its extension says and decodes every pixel (415 "The uploaded file is not a png picture" otherwise: a web page, a JPEG called `.png`, a file that only starts like a PNG, one cut short); at most 25 million pixels (413), checked before decoding, so a small file holding a huge picture is refused. The public copy is made from those very bytes. `confirm` locks the user's row (for a logo, then the company's too) until it has saved, so two confirms of the same upload at once publish it once (the other gets 400). Then the file of the previous avatar (or logo) is deleted; if a delete fails, the request still succeeds and the file left behind is logged. `DELETE /users/me` and `DELETE /companies` take the same locks and read the picture key again under them: a confirm that meets a deletion either comes first, and the deletion then deletes its new file, or waits for it and publishes nothing, getting the answer of a deleted account (401) or of a user without a company (404).
- Company logo routes are for employers: a user with a company that is not deleted (404 "You have no company" otherwise).
- `logo_url` in `CompanyOut` (`GET /companies/me`, `POST /companies`, `PATCH /companies/me`): the logo's public address, or `null` without a logo (there is no default logo). `DELETE /companies` empties the logo with the soft delete and deletes its file at once, as `DELETE /users/me` does for the avatar and the logo.
- Default avatar: a user with no picture gets `avatar_url` = `DEFAULT_AVATAR_URL`, by default `/api/media/avatar/default.svg` on our own site, a grey picture the API serves itself (no login, cached for a day).
- `avatar_url` in the public profile and in the friends list comes from `Storage.avatar_url` (BE-22): each user's public picture address or `DEFAULT_AVATAR_URL`.

## Game

Join the queue over REST, listen for room and phase events on `/ws`, open `/ws/game` (BE-09) for room chat, vote over REST (BE-10), and fetch results when finished (BE-10).

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/game/queue/join` | Bearer | — | 202 `{message: "queued", room_id}` | 409 already in active room |
| DELETE | `/game/queue/leave` | Bearer | — | 204 | — |
| GET | `/game/rooms/{id}` | Bearer (participant) | — | 200 `{id, state, target_size, participant_count, my_participant_id, room_expires_at, phase_ends_at, participants: [{id, display_label, is_you}]}` | 403, 404 |
| POST | `/game/rooms/{id}/start` | Bearer (participant) | — | 200 `RoomOut` (starts waiting room at 2–4 participants; idempotent if already `discussion`) | 403, 404, 409 outside 2–4 participants or wrong state |
| POST | `/game/rooms/{id}/votes` | Bearer (participant) | `{target_participant_id, guess: "bot" or "human"}` | 201 `{message}` | 400 self, 409 not voting phase / already voted, 422 |
| GET | `/game/rooms/{id}/results` | Bearer (participant) | — | 200 `{room_id, state, participants: [{participant_id, display_label, is_bot, score (humans), deception_rate (bots)}]}` | 409 not finished |

Room states (BE-27): `waiting (180 s max) → discussion (120 s) → voting (45 s) → finished`, or `closed` if timer expires with 1 participant or the last human leaves `waiting`. Every participant payload before results exposes only `{id, display_label, is_you}` identically for humans and bots, where `id` and `my_participant_id` are the participant's stable room label number (1–5, e.g. 2 for "Player 2"), never database participant ids (BE-35).

## System

Health and spec endpoints of the new backend (BE-01). Routes under `/_internal/*` and `/metrics` are not part of this contract: they are left out of the OpenAPI spec and blocked by the front proxy (404 externally, reachable only inside the Docker network).

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/health` | — | — | 200 `{status: "ok" \| "degraded", components: {db, redis, minio, worker}}` | 503 `{status: "down", components: {db, redis, minio, worker}}` (core down) |
| GET | `/api/openapi.json` | — | — | 200 OpenAPI 3.1 spec of every public route | — |
| GET | `/api/docs` | — | — | 200 Swagger UI, only when `ENV=dev` | 404 otherwise |
| GET | `/api/docs/oauth2-redirect` | — | — | 200 Swagger UI's OAuth helper page, only when `ENV=dev` | 404 otherwise |
| GET | `/metrics` (internal only) | — | — | 200 Prometheus text exposition (`http_requests_*`, `ws_connections`) | 404 externally via proxy |

## WebSocket protocol

One socket per tab on `/ws`; every frame is JSON `{type, payload}`. Delivery is per user, not per socket: an event for a user reaches every socket that user has open, including `/game/ws`, so the client must route by `type` and ignore what it does not know.

**Connect (new backend, BE-06):** the access token never goes into the socket's URL, where proxy logs would keep it. First ask for a one-time ticket over HTTP, then open the socket with it:

| Method | Path | Auth | Request | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/api/ws/ticket` | Bearer | — | 200 `{ticket}`: opens one socket, once, within 30 s | 401 |
| WS | `/ws?ticket=<ticket>` | the ticket | — | the socket stays open | closed with code 1008 |

- Every connect and reconnect needs a new ticket. A ticket works on any API worker (tickets live in Redis).
- **1008** (reason `"Invalid or expired ticket"`): no ticket, an unknown, expired or already used ticket, a deleted user, or a password changed since the ticket was made (`token_version`). The server accepts the socket and then closes it, so the browser sees 1008, not a failed handshake. Get a new ticket (refreshing the access token first if it is old) and connect again.
- **1011**: the server lost its link to Redis and can no longer deliver events to this socket. Reconnect with backoff, as below.
- The reference connected with `?token=<access_token>`; the new backend does not accept it. The game room socket moves to `wss://<host>/ws/game?ticket=<ticket>&room_id=<id>` with the same ticket check (BE-09), closed 1008 if not a participant.

| Direction | `type` | Payload | When |
| --- | --- | --- | --- |
| client → server | `ping` | — | Keep-alive; send every 25–30 s. It also keeps you online: a socket that has not pinged for 60 s stops counting as online |
| client → server | `delivered` | `{message_id}` (top-level or inside `payload`) | Message shown on this device |
| client → server | `read` | `{conversation_id, last_message_id}` (top-level or inside `payload`) | Conversation opened / scrolled to bottom |
| client → server (`/game/ws`) | `chat_message` | `{text}` at top level | Player sends a room message during discussion |
| server → client | `pong` | `null` | Reply to ping |
| server → client | `presence` | `{user_id, is_online}` | A friend's first socket opened (`true`) or last socket closed (`false`); see below |
| server → client | `message` | `MessageOut` | New message in any of my conversations (mine too) |
| server → client | `message_updated` | `MessageOut` | Author edited a message within 15 min (BE-24) |
| server → client | `message_deleted` | `{id, conversation_id}` | Author soft-deleted a message (BE-24) |
| server → client | `message_status` | `{message_id, status: "delivered"}` | A participant marked it delivered |
| server → client | `conversation_updated` | `{conversation_id, unread_count}` (`null` for the other side) | Someone read a conversation |
| server → client | `game_room_formed` | `{room_id}` | Matchmaking put me in a room |
| server → client | `game_participant_joined` | `{room_id, participant: {id, display_label}, participant_count, room_expires_at}` | A human or bot joined the waiting room (`participant.id` is label number 1–5, BE-35) |
| server → client | `game_participant_left` | `{room_id, participant: {id, display_label}, participant_count, room_expires_at}` | A human left the waiting room (`participant.id` is label number 1–5, BE-35) |
| server → client | `game_started` | `{room_id, state: "discussion", phase_ends_at}` | Waiting room transitioned to discussion |
| server → client | `game_room_closed` | `{room_id}` | Waiting room expired with 1 participant |
| server → client | `game_message` | `{id, participant_id, display_label, text}` | Room message from a player or a bot (`participant_id` is label number 1–5, BE-35) |
| server → client | `game_phase_voting` | `{room_id, state: "voting", phase_ends_at}` | Discussion ended |
| server → client | `game_phase_finished` | `{room_id}` | Voting ended, results ready |

- **Unread counts in `conversation_updated`**: For the reader who emitted the read receipt, `unread_count` is their updated **total unread messages count** across all conversations (matching `GET /conversations/unread`), allowing the client to update global navigation badges directly while setting that specific conversation row's unread counter to 0. For other participants in the room, `unread_count` is `null`.
- **Receipt envelopes**: Client-sent `delivered` and `read` frames are accepted both at top level (`{"type": "delivered", "message_id": 6}`) and inside a `payload` dictionary (`{"type": "delivered", "payload": {"message_id": 6}}`).

**Presence (new backend, BE-06):** a user is online while at least one of their sockets is open and pinging, on any API worker; the count lives in Redis. Only friends (accepted friendships) get `presence` events, and only on a change: the first socket of the user opening, or the last one closing. Several tabs count as one user. If an API process stops without closing its sockets, friends get no `false` event; that user stops counting as online at most 60 s later. To show who is online when a page opens, use the `is_online` field of the REST answers (friends list, public profile), then follow the events.

**Client rules:** reconnect with backoff (1 s, 2 s, 5 s, then every 10 s) and after reconnecting reload what you show (conversation list, open messages, room state, who is online), because events sent while offline are lost. Refresh the access token before reconnecting, and get a new ticket for every connect.

## Planned changes for the new backend

The frontend should code against these from day one; the backend Tech Lead confirms each one before it lands and ticks it here.

| Done | Change | Why |
| --- | --- | --- |
| \[ \] | All routes under `/api`, WebSockets under `/ws` and `/ws/game` on the same origin | One origin through the nginx + ModSecurity front proxy: no CORS, no mixed content |
| [x] | `GET /companies/me` → 200 `null` when the user has no company | No 404 in the Chrome console |
| [x] | `UserOut`, public profile, friends list return `avatar_url` (signed or public path) with a default avatar; same for `logo_url` | Frontend cannot show images from object keys |
| \[x\] | `PATCH /users/me` accepts partial updates | Edit one field without resending the whole profile |
| \[x\] | Drop `phone`, `is_phone_verified`, `username`, `account_number` from `UserOut` unless a feature uses them | Smaller contract, no dead fields |
| \[x\] | Email links open frontend routes `/verify-email?token=` and `/reset-password?token=`, which call the API | Links currently show raw JSON or 405 |
| \[x\] | WebSocket auth with a one-time ticket: `POST /api/ws/ticket` → `{ticket}` valid 30 s, then `wss://<host>/ws?ticket=` (BE-06) | Access tokens no longer in URLs and logs |
| \[ \] | New events `message_updated`, `message_deleted`, `presence` `{user_id, is_online}`, `video_moderated` `{id, moderation_status}` (`presence` is sent since BE-06) | Live edits, online dots, no polling for moderation |
| \[ \] | Game: `GET /api/game/rooms/{id}/messages`; room payload and phase events include `phase_ends_at`; results include `winner_participant_ids` | Reconnect, countdown, clear win / loss |
| \[ \] | Game: minimum room size 3; votes must target the same room | Multiplayer 3+ module; integrity |
| \[ \] | Game votes: `POST /game/rooms/{id}/votes` names its target by label number (1–5) instead of `target_participant_id`. A vote request replaces the voter's mark for that target: it is idempotent and allowed any number of times until voting ends, so there is no "already voted" error. A target without a mark counts as `human`. BE-10 owns the final field names and errors. Rules: [game/turing-duel-rules.md](../game/turing-duel-rules.md), sections 5, 6 and 9 | Marks preset to human and changeable until voting ends; no database ids before results (DOC-08 follow-up, BE-10) |
| [x] | Game payloads before the results name each participant by its label number (1–5, "Player N"), the same field as in the votes row above, never by the database participant id: `GET /game/rooms/{id}` (`my_participant_id` and `participants[].id`), `game_participant_joined` and `game_participant_left` (`participant.id`), and `game_message` (`participant_id`). `display_label` stays. Database participant ids appear only in `GET /game/rooms/{id}/results`. BE-35 (Nader, new card: hide database participant ids from game payloads before results) owns the REST room state and the room events; BE-09 owns `game_message` on `/ws/game`. Rules: [game/turing-duel-rules.md](../game/turing-duel-rules.md), section 9 | No database ids before results, so ids cannot hint at join order or at bots (DOC-08 follow-up, BE-35, BE-09) |
| \[ \] | Game results add `winner_participant_ids` (ids of the participants with outcome `win`; empty on a draw), `is_draw` (boolean: the top score is shared, or the single human scored 0) and per participant `outcome` (`win`, `draw` or `loss` for humans; `null` for bots). Rules: [game/turing-duel-rules.md](../game/turing-duel-rules.md) | Clear win / draw / loss result (DOC-08, BE-10) |
| \[ \] | Jobs: `active` renamed `draft`; only `open` jobs accept applications or chats | One clear meaning per status |
| \[ \] | Remove `/chat/*`, `/media/intro-video/draft/*`, `/media/feed/demo`, `/media/health` (moved to `/_internal`) | Legacy and leaks |
| \[ \] | OAuth: `GET /api/auth/oauth/42/start` → redirect; `GET /api/auth/oauth/42/callback` → token pair | OAuth module (tier B) |
| [x] | `GET /metrics` for Prometheus, internal only | Monitoring module |

The `avatar_url` row (BE-08 + BE-22): `UserOut` (`avatar_url`), `CompanyOut` (`logo_url`), `GET /api/friends`, and `GET /api/users/{id}/profile` all return public/default image URLs through `Storage.avatar_url` / `Storage.logo_url`.

## Machine-readable spec

The reference spec is exported as `wozu-reference-openapi.json` (OpenAPI 3.1, 62 paths, shared alongside this doc); WebSockets are not in it, see the protocol above.

- **Reference:** the spec is served at `/_internal/openapi.json` and Swagger at `/_internal/docs`, both behind the `X-Internal-Key` header. To regenerate without a running stack: `python -c "import json; from app.main_ft import app; print(json.dumps(app.openapi()))"` with the env vars from `.env.example`.
- **New backend:** serve Swagger at `/api/docs` in development; the frontend generates TypeScript types from `/api/openapi.json` with `openapi-typescript`, so a contract change shows up as a compile error, not a runtime bug.
- **Rule:** a PR that changes the API updates this doc in the same card.
