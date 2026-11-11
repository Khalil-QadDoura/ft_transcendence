# FE-09 — own profile

Owner: Zayid Elkahir. [Trello card](https://trello.com/c/oDGDnO4g).

The authenticated `/profile` route reads Khalil's `GET /api/users/me`. Email is read-only. First name, last name, position, date of birth and biography use Ahmad's shared Input, Textarea and Button. Only changed fields are submitted to `PATCH /api/users/me`; an untouched incomplete field does not prevent editing another field. FE-03 validates trimmed code-point limits and age 18+. Backend 422 details appear under the rejected input with focus. Failed saves retain edits; success and the query cache update only after the backend accepts the patch. A profile link opens account settings.

The saved name and position drive the completeness hint. It describes profile completeness, not eligibility for every backend application rule. Discard restores the last successful response. Query refetches do not erase a draft. The editor is keyed by user ID and the shared auth provider clears private caches on session replacement.

## Avatar boundary

The frontend implements the current BE-08 contract: JPG/PNG/WebP, non-empty image up to 5 MiB, revocable local preview, signed URL request, raw PUT with progress, confirm, then refreshed profile. The PUT uses no API bearer header, accepts only same-origin `/files/` URLs, has a timeout and aborts on unmount. Confirmation never runs after a failed PUT. Client checks are usability checks; backend validation remains authoritative.

BE-08 #27 is now merged on main at `ee32922` and supplies `avatar_url` and the upload endpoints. This branch includes that backend. A present nullable `avatar_url` enables the upload controls; older backends still show an availability message. Confirmation HTTP 415 clears the invalid preview and asks for another JPG, PNG or WebP; network and server errors preserve the selection for retry. Component tests exercise both outcomes. The full browser upload journey through the deployment proxy remains a validation gate; mocked upload tests do not validate MinIO or proxy configuration.

## Dependency order and localization

This PR is stacked on `feat/FE-05-password-settings` (#34), which uses `integration/FE-05-prerequisites` for #17 + #31. Do not merge into a feature/integration branch. Merge approved parent work to main first, retarget each child, resolve conflicts and repeat checks. The integration branch preserves #17's rotation logic and adds Accept-Language to rotateToken.

Copy uses an English `profile` i18next namespace, with explicitly declared English fallback for the other four languages. FE-07 owns full translation and FE-08 full RTL review. The layout uses logical spacing and shared ivory/olive/lime tokens. No claim of complete multilingual content is made.

## Validation, November 11, 2026

- Unit/component coverage: partial saves from incomplete profiles, age validation and focus, server field detail, failed-save retention/retry, load retry, image type/size, upload URL restriction, progress/abort and confirmation ordering.
- Live integration uses the actual merged backend and disposable loopback PostgreSQL/PostGIS with captured email. Three journeys cover auth, recovery/settings, and GET/PATCH persistence including backend underage rejection. No production accounts or real email delivery.
- Run `npm test`, `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run i18n:check`, `npm run legal:check`, `npm run build` in frontend. Live test setup is in `docs/auth-screens.md`; use `WOZU_TEST_BACKEND_URL` with `npm exec -- vitest run --config scripts/auth-backend.config.ts`.
- The backend limits registration to 5/minute. Use a fresh disposable harness or wait for its window before rerunning the full integration suite. Do not weaken production limits.
- Build currently warns that the application bundle exceeds 500 kB; route splitting remains a follow-up.

## Study and defense

Explain why a partial patch differs from replacing the full profile, why an HTML date is not a timezone conversion, why UI size/type checks do not secure storage, and why confirmation must follow the successful byte upload. Trace a server rejection through ApiError, the field adapter and the accessible input. For personal practice, change the biography hint, run the focused tests and show the change live; an agent run does not count as the owner's demonstration.
