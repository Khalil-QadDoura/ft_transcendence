# FE-04 — authentication screens with the FE-20 client

Owner: Zayid. [Card](https://trello.com/c/uP8wCVRt). Integration updated November 10, 2026.

## Behavior and ownership

Registration, verification, login and logout call Ahmad's shared FE-20 client through a thin `AuthGateway`. The old independent HTTP/token store is removed. Login, register, verify and logout use `skipAuth: true`, so a wrong-password 401 never triggers refresh. Only email/password are submitted; confirmation stays in the form. Shared `ApiError` status and detail map to the existing field-error adapter and user-facing messages.

`AuthProvider` restores a saved session on mount. Protected routes stay in `loading` until the backend accepts or rejects the refresh token; React StrictMode uses the same refresh promise. A successful reload keeps the protected path, query and hash. An invalid refresh clears credentials and preserves the destination in the login return URL. The FE-20 client holds access tokens in memory and refresh tokens in localStorage, with tab-memory fallback if storage is unavailable. Storage failure means reload requires login. Script-readable storage is an XSS exposure; memory-only access tokens do not eliminate XSS risk.

The client refreshes at 14 minutes for Khalil's 15-minute access lifetime, deduplicates concurrent requests within the document, and retries a protected 401 once. A delayed 401 reuses an already-rotated access token. Login/logout changes a session version; late requests cannot overwrite a newer session or return the previous user's data. Private query data clears before notifying route consumers on session replacement, but ordinary rotation preserves the same user's cache.

Logout clears the browser immediately, then revokes the saved refresh token and any replacement produced by a refresh already in flight. This matters because BE-03 revokes a particular refresh token, not every session. Failed revocation keeps the existing local-sign-out warning. BE-03 access tokens remain valid on the server until expiry; the browser discards its copy. No backend behavior was changed.

The screen layout, accessible labels, pending states, verification single-flight behavior and safe redirects remain. Privacy/Terms content, post-login feature screens and FE-21 primitive adoption are separate tickets.

## Dependency and review base

`integration/FE-04-prerequisites` now combines current main (`07d4f92`), FE-02 #2, FE-03 #14 and Ahmad's FE-20 #22 at `856a4b17eafc9be9625abc21f8c95f40cf50d008`. Ahmad's original commits are retained. Session-lifecycle corrections in the FE-04 diff are included for Khalil to review alongside the adapter.

Do not merge FE-04 into this temporary branch. After #2, #14 and #22 land, transplant the FE-04-only changes onto main, retarget PR #17, resolve any client differences and repeat checks. This integration does not merge or rewrite Ahmad's PR.

## Verified backend contract

The November 10 integration runs against Khalil's merged auth/users implementation on main `07d4f92aca3b103cc16435757aeb60371e71682b`, backend tree `f338aca380938a48e0b2620388143b32e64263fc`, PostgreSQL 16 + PostGIS.

| Action          | Request                                 | Result                                               |
| --------------- | --------------------------------------- | ---------------------------------------------------- |
| Register        | POST /api/auth/register, email/password | 202; check-email state, no session                   |
| Verify          | GET /api/auth/verify?token=...          | 200 verified:true; invalid link 400                  |
| Login           | POST /api/auth/login, email/password    | 200 bearer pair; 401 bad credentials; 403 unverified |
| Restore/refresh | POST /api/auth/refresh, refresh_token   | 200 replacement pair; consumed/revoked token 401     |
| Profile probe   | GET /api/users/me with bearer access    | 200 authenticated profile; invalid access 401        |
| Logout          | POST /api/auth/logout, refresh_token    | 204; later reuse of that refresh token returns 401   |

The generated schema is still the initial reference snapshot. Runtime login/refresh response checks follow the actual team contract. Requests retain the /api prefix by default; use `API_PROXY_STRIP_PREFIX=true` only for the old reference backend.

## Automated and browser checks

Normal commands from frontend: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm test`, `npm run build`. The 109 unit/component tests cover the existing screens plus restoration under StrictMode, 422 propagation, wrong-password no-refresh, private-cache separation, rotation single-flight, late requests, malformed refresh data, storage restrictions, bounded retries and logout during rotation. These tests use mocked HTTP responses.

The opt-in live test uses the actual gateway/client with a disposable database. It exercises register → unverified rejection → verify → wrong-password rejection → login → bearer profile → fresh-module restoration → three concurrent protected requests with invalid access → one refresh → logout → rejected refresh-token reuse. It creates a synthetic @example.com account. Never use production data.

1. Prepare a local disposable PostgreSQL/PostGIS database with `test` in its name; install the backend's requirements-dev.txt into a Python environment.
2. Set `TEST_DATABASE_URL` to its `postgresql+asyncpg://...` URL in the environment. Run `python frontend/scripts/serve-auth-test-backend.py` from the repository root. The harness applies migrations and listens only on 127.0.0.1:8010. It overrides email delivery only; it must never be deployed. Credentials are not written into source.
3. In another terminal, from frontend, set `WOZU_TEST_BACKEND_URL=http://127.0.0.1:8010` and run `npx vitest run --config scripts/auth-backend.config.ts`.
4. For browser checks, set `API_PROXY_TARGET=http://127.0.0.1:8010` and run `npm run dev -- --port 5178`. Captured test messages appear at http://127.0.0.1:8010/__review/inbox. Stop the harness after testing. Test records remain in the disposable database until its owner removes it.

Browser verification on November 10: register, captured-email verification, login returning to /friends, loading during reload then restored /friends, and sign-out. The checked normal-flow tab had no captured warnings/errors. This is real local auth/database evidence, not real SMTP or final HTTPS deployment evidence. The prior November 8 responsive/keyboard checks are historical; this integration does not redesign the screens.

## Remaining gates

Khalil's review, prerequisite merges, main-based CI and the owner walkthrough remain. Final HTTPS/Mailpit deployment is infrastructure scope. Refresh single-flight is document-local; cross-tab rotation coordination is not implemented here. The opt-in test does not run automatically in CI because it requires the disposable backend; CI runs unit/component tests and the frontend Docker build.
