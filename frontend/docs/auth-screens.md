# FE-04 — authentication screens with the FE-20 client

Owner: Zayid. [Card](https://trello.com/c/uP8wCVRt). Integration updated November 10, 2026.

## Behavior and ownership

Registration, verification, login and logout call Ahmad's shared FE-20 client through a thin `AuthGateway`. The old independent HTTP/token store is removed. Login, register, verify and logout use `skipAuth: true`, so a wrong-password 401 never triggers refresh. Only email/password are submitted; confirmation stays in the form. Shared `ApiError` status and detail map to the existing field-error adapter and user-facing messages.

`AuthProvider` restores a saved session on mount. Protected routes stay in `loading` until the backend accepts or rejects the refresh token; React StrictMode uses the same refresh promise. A successful reload keeps the protected path, query and hash. An invalid refresh clears credentials and preserves the destination in the login return URL. The FE-20 client holds access tokens in memory and refresh tokens in localStorage, with tab-memory fallback if storage is unavailable. Storage failure means reload requires login. Script-readable storage is an XSS exposure; memory-only access tokens do not eliminate XSS risk.

The client refreshes at 14 minutes for Khalil's 15-minute access lifetime, deduplicates concurrent requests within the document, and retries a protected 401 once. A delayed 401 reuses an already-rotated access token. Login/logout changes a session version; late requests cannot overwrite a newer session or return the previous user's data. Private query data clears before notifying route consumers on session replacement, but ordinary rotation preserves the same user's cache.

Logout clears the browser immediately, then revokes the saved refresh token and any replacement produced by a refresh already in flight. This matters because BE-03 revokes a particular refresh token, not every session. Failed revocation keeps the existing local-sign-out warning. BE-03 access tokens remain valid on the server until expiry; the browser discards its copy. No backend behavior was changed.

The screen layout, accessible labels, pending states, verification single-flight behavior and safe redirects remain. Privacy/Terms content and post-login feature screens are separate tickets. The form now uses FE-21 Input/Button and shared color tokens.

## Dependency and review base

FE-02, FE-03, FE-20 and FE-21 are merged. PR #17 targets main and includes the merged legal pages. Khalil reviews the backend contract; Ahmad reviews the shared-client lifecycle and component changes. Cross-tab rotation coordination remains separate.

## Verified backend contract

The November 10 integration runs against Khalil's merged auth/users implementation on main `07d4f92aca3b103cc16435757aeb60371e71682b`, backend tree `f338aca380938a48e0b2620388143b32e64263fc`, PostgreSQL 16 + PostGIS.

| Action          | Request                                 | Result                                                             |
| --------------- | --------------------------------------- | ------------------------------------------------------------------ |
| Register        | POST /api/auth/register, email/password | 202 for new/unverified email; 409 for an existing verified account |
| Verify          | GET /api/auth/verify?token=...          | 200 verified:true; invalid link 400                                |
| Login           | POST /api/auth/login, email/password    | 200 bearer pair; 401 bad credentials; 403 unverified               |
| Restore/refresh | POST /api/auth/refresh, refresh_token   | 200 replacement pair; consumed/revoked token 401                   |
| Profile probe   | GET /api/users/me with bearer access    | 200 authenticated profile; invalid access 401                      |
| Logout          | POST /api/auth/logout, refresh_token    | 204; later reuse of that refresh token returns 401                 |

The generated schema is still the initial reference snapshot. Runtime login/refresh response checks follow the actual team contract. Requests retain the /api prefix by default; use `API_PROXY_STRIP_PREFIX=true` only for the old reference backend.

## Automated and browser checks

Normal commands from frontend: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm test`, `npm run build`. The initial integration had 109 unit/component tests covering the existing screens plus restoration under StrictMode, 422 propagation, wrong-password no-refresh, private-cache separation, rotation single-flight, late requests, malformed refresh data, storage restrictions, bounded retries and logout during rotation. These tests use mocked HTTP responses. The review follow-up adds the verified-email 409 message, empty-password prevention, server field-detail rendering and the merged shared-component tests.

The live integration test uses the actual gateway/client with a disposable database. It exercises register → repeat unverified registration → unverified login rejection → verify → verified-email 409 → wrong-password rejection → login → bearer profile → fresh-module restoration → three concurrent protected requests with invalid access → one refresh → logout → rejected refresh-token reuse. It creates a synthetic @example.com account. Never use production data.

1. Prepare a local disposable PostgreSQL/PostGIS database with `test` in its name; install the backend's requirements-dev.txt into a Python environment.
2. Set `TEST_DATABASE_URL` to its `postgresql+asyncpg://...` URL in the environment. Optionally set `TEST_REDIS_URL` or `REDIS_URL` (defaults to loopback `redis://127.0.0.1:6379/1`). Run `python frontend/scripts/serve-auth-test-backend.py` from the repository root. The harness applies migrations and listens only on 127.0.0.1:8010. It overrides email delivery only; it must never be deployed. Credentials are not written into source.
3. In another terminal, from frontend, set `WOZU_TEST_BACKEND_URL=http://127.0.0.1:8010` and run `npx vitest run --config scripts/auth-backend.config.ts`.
4. For browser checks, set `API_PROXY_TARGET=http://127.0.0.1:8010` and run `npm run dev -- --port 5178`. Captured test messages appear at http://127.0.0.1:8010/__review/inbox. Stop the harness after testing. Test records remain in the disposable database until its owner removes it.

Browser verification on November 10: register, captured-email verification, login returning to /friends, loading during reload then restored /friends, and sign-out. The checked normal-flow tab had no captured warnings/errors. This is real local auth/database evidence, not real SMTP or final HTTPS deployment evidence. The prior November 8 responsive/keyboard checks are historical; this integration does not redesign the screens.

## Remaining gates

Khalil's review, prerequisite merges, main-based CI and the owner walkthrough remain. Final HTTPS/Mailpit deployment is infrastructure scope. Refresh single-flight is document-local; cross-tab rotation coordination is not implemented here. The frontend workflow now runs this integration test against the actual backend with a disposable PostGIS service and captured email. Frontend and backend changes trigger it. CI also runs unit/component tests and the frontend Docker build. The capture-mail harness is loopback-only and must never be deployed.

## Review follow-up — November 10

A verified email that returns HTTP 409 shows “This email already has an account. Try signing in.” The existing sign-in link preserves `next`; a repeated unverified registration still follows the 202 check-inbox flow. Empty login passwords are rejected locally while short nonempty passwords still reach the backend. Backend 422 field explanations render as ordinary React text and retain field focus.

Transient refresh failures (429, 5xx or offline), cross-tab rotation coordination and shared UI primitive adoption remain follow-up work discussed in review; they are not claimed fixed by this message-handling change. A new browser pass is pending because browser access was unavailable in the review-fix session; the earlier browser evidence above is historical.

## November 11 follow-up

Transient refresh failures (429, 5xx and offline) now preserve the current credentials and schedule one retry after 30 seconds. The shared promise still deduplicates refresh requests. Logout/new login cancels retries; a rejected 401 or structurally invalid token response still clears credentials. Protected startup stays at its original URL while refresh is unavailable and offers a retry message. This avoids treating rate limiting as revoked credentials.

Auth forms now use Ahmad’s shared Input and Button, including accessible field errors, loading and Tailwind focus/spacing. Auth CSS uses the shared color tokens. Auth interface copy is extracted into `copy.en.json` for the FE-06/FE-07 integration; server validation details remain plain React text. English wording is preserved. These changes supersede the earlier “transient refresh/shared primitives pending” notes; cross-tab coordination and final HTTPS/SMTP validation remain open.

## Login with 42 (BE-11) — November 19

Khalil's BE-11 adds a "Log in with 42" link under the login form (not on the sign-up page). It is a plain link to `/api/auth/oauth/42/start`, not a router `Link`: the browser leaves the app, and the API sends it on to 42 intra. The backend's callback brings the browser back to `/oauth/callback` with the token pair after the `#` (`#access_token=…&refresh_token=…&token_type=bearer`), or with `#error=<reason>`; the part after `#` never reaches a server or a log.

`OAuthCallback` reads that fragment once, stores the pair through `AuthGateway.loginWithTokens` (the same `clearTokens` + `setTokens` as a password login: access token in memory, refresh token in localStorage) and replaces the address with `/profile`, so the tokens leave the address bar and the history. Each reason (`access_denied`, `invalid_state`, `ft_unavailable`, `no_email`, `account_disabled`; anything else, or a broken pair, gets a general message) is explained with a link back to `/login`. The route sits outside `GuestOnly`, and `safeNext` never returns to it. A `next` destination is not carried through 42: after a 42 login the user lands on `/profile`. The backend contract is in `docs/api/api-contract.md` ("Login with 42 in the new backend").
