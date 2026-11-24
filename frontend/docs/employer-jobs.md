# FE-27 — Employer job management

Owner: Zayid Elkahir. Sprint 3. Dependency: merged BE-25.

Authenticated routes `/employer/jobs`, `/employer/jobs/new`, and
`/employer/jobs/:id/edit` use Ahmad's shared API client against the merged backend.
The list shows server-provided views, applications and new-application counters.
Creation defaults to draft; editing can publish. Deletion requires confirmation,
keeps failures inside the dialog, and refreshes cached listings after success.

The backend requires an active company. A 404 from `/jobs/mine` explains this
prerequisite. Company onboarding is a separate feature; this change does not
invent an endpoint or bypass it. The editor only exposes records in `/jobs/mine`,
and server ownership checks remain authoritative. Salary blanks become null;
zero remains zero. Coordinates and enumerations mirror BE-25 validation.

## Verification

On November 22, 2026: 273 frontend tests passed, along with typecheck, lint,
translation-key checks, formatting and production build. An existing large-bundle
warning remains. Browser verification covered authenticated creation and the
updated list; the 360px viewport had no horizontal document overflow and the
browser error log was empty. The editor uses logical CSS properties for RTL.

Run the opt-in lifecycle test against the disposable captured-mail backend
documented in `auth-screens.md`:

```sh
WOZU_TEST_BACKEND_URL=http://127.0.0.1:8010 npx vitest run --config scripts/employer-backend.config.ts
```

This test passed against main 70340dd with real PostgreSQL/PostGIS and Redis.
It registers/verifies two temporary users, checks the company prerequisite,
creates a draft, publishes with zero salary, rejects cross-owner update/delete,
and verifies soft deletion. It uses the actual frontend API adapter and backend;
only outgoing test email is captured. Never run it against real accounts.

## Follow-up boundaries

FE-07 supplies complete translations; the new employer namespace explicitly
declares English fallback. FE-28 (Ahmad) owns the applications workflow.
Cross-pair review and current-head CI are required before merge.

## Study exercise

Trace `JobEditor` → `jobForm` → `employerApi.save` → shared authenticated client
→ BE-25 ownership checks → query invalidation. Explain why client-side filtering
does not authorize writes, why a blank salary differs from zero, and why a failed
delete must preserve the dialog and selected ID. In a disposable practice branch,
change a coordinate boundary and demonstrate the corresponding validation test.
This is a suggested exercise, not a claim that personal practice is complete.
