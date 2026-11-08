# FE-04 — auth screens and FE-20 handoff

Owner: Zayid. [Card](https://trello.com/c/uP8wCVRt). Implemented with Codex assistance on November 8, 2026 (America/Los_Angeles).

## What this PR demonstrates

The old login/register/verify route placeholders become accessible forms and result screens. Registration uses FE-03 validation plus a frontend-only password confirmation. Only email and password go over the wire. A successful registration does not establish a session; verification confirms the email, and a successful backend login establishes the session. Logout clears local state even when server revocation fails, with an explicit warning in that case.

The shared footer and safe `?next=` return route remain available. Inputs have labels, described errors, first-invalid-field focus, autocomplete and pending states. A password visibility control is keyboard operable. Expected 401, 403 and 429 failures have human-readable messages; backend 422 responses use FE-03's allowlisted field mapping. Raw exceptions and tokens are not rendered or logged. Invalid, missing, replaced and temporarily unavailable verification links have distinct recovery paths. Verification is single-flight under React StrictMode and ignores a previous token's late result.

## Merge dependencies — not a completed FE-20

FE-02 (#2) and FE-03 (#14) are unmerged prerequisites. `integration/FE-04-prerequisites` combines their existing commits with main solely as a review base. Do not merge this PR into that branch. Once both parent PRs land, transplant only FE-04's commit(s) onto main, retarget this PR and rerun checks.

Ahmad's FE-20 shared client is not available at this revision. `gateway.ts` is an **interim auth-only HTTP bridge**, behind the injectable `AuthGateway` interface. It retains the refresh token only in this tab's memory for logout. The returned access token is validated but not exposed to domain clients; other data screens are not implemented here. Reload requires login, and the session returns to anonymous after the backend's 15-minute access lifetime. There is no persisted session, automatic refresh, generic API client, bearer injection or 401 retry. Those remain Ahmad's FE-20 scope. This PR is ready for review of the screens, **not final FE-04 acceptance or merge** until that handoff is complete.

Ahmad's adapter should implement `register`, `verify`, `login`, `logout`, `getStatus` and `subscribe`, map shared `ApiError` to `AuthError` without losing the backend payload, and pass it to `AuthProvider client={...}`. Establish `authenticated` only after a successful login/refresh; expose `loading` during restoration; notify on logout or refresh failure. Clear user-specific query data on identity changes, including account replacement when the status stays authenticated. FE-20 owns the access token in memory, documented refresh-token storage, refresh single-flight and retry policy. The intermediate bridge should then be removed, not kept as a competing session store.

Ahmad's FE-21 primitives are also absent. Styles are local to auth; this does not claim his shared theme/component ticket. Replace local fields/buttons with those primitives when available without changing the form and gateway contracts.

## Verified backend contract

Tested against Khalil's BE-03 commit `80dc3813ff6ad076c53101d620c83aff584885dc`, not the obsolete reference auth implementation. BE-03 merged during review as `56eef6141f6359c133126351ad3661d7d34a512a`; its backend tree is identical (`15c8a0b130f662f15bade70312083e6bcf17d6af`) to the tested revision:

| Action   | Request                                       | Expected result                                                       |
| -------- | --------------------------------------------- | --------------------------------------------------------------------- |
| Register | `POST /api/auth/register`, `{email,password}` | 202; check-email message                                              |
| Verify   | `GET /api/auth/verify?token=...`              | 200 with `verified:true`; invalid/replaced link 400                   |
| Login    | `POST /api/auth/login`, `{email,password}`    | 200 bearer access/refresh pair; 401 wrong credentials; 403 unverified |
| Logout   | `POST /api/auth/logout`, `{refresh_token}`    | 204; local state cleared even on network failure                      |

The generated reference schema predates BE-03; the small runtime response validators here follow BE-03's actual schemas. No backend endpoint or contract was changed by FE-04.

## Run and evaluate

Use Khalil's fixed BE-03 backend, a disposable PostgreSQL/PostGIS database, and local SMTP/Mailpit. Set backend `FRONTEND_BASE_URL` to your frontend origin. In the frontend `.env`, set `API_PROXY_TARGET` to that backend and `API_PROXY_STRIP_PREFIX=false`; then `npm ci` and `npm run dev`. Production HTTPS and Mailpit routing at `https://localhost/mail` belong to infrastructure. The inbox hint is shown only in development builds.

Required checks: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm test`, `npm run build`. The suite has 81 passing tests at delivery, including registration, login, logout and verification failure cases. CI also builds the Docker image.

Observed local browser flow: registration → blocked unverified login → captured verification email → success → wrong password → successful login returning to `/friends` → logout. This used the real backend and database with a **test-only captured-mail dependency**, not actual SMTP delivery. The capture inbox is outside the repository and must never be deployed. Captured console warning/error entries were empty for the tested auth tab; deliberate negative HTTP responses were checked separately from normal success behavior.

Desktop inspection used the normal 1280px browser viewport. A 360px same-origin iframe was used after the browser viewport override did not take effect; its measured document and scroll widths were both 360px, with error focus on email and accessible footer links. Keyboard Tab moves from email to password. This is responsive layout evidence, not a claim of physical-phone testing.

Remaining acceptance: FE-20 integration and refresh/reload tests, real SMTP/Mailpit delivery through the final HTTPS stack, fresh human review, green CI on the final main-based head, and Zayid's teach-back. Privacy/Terms contents and post-login feature slots remain separate tickets.
