# FE-10 / FE-11: public profiles and friends

Owner: Zayid Elkahir. FE-10 is PR #50; FE-11 is PR #51. BE-22 #41 is merged.

The shared client calls the real `/users/{id}/profile`, `/friends`, `/friends/requests`
and `/conversations` endpoints. Public profile responses always include a nullable
`friendship_id`; accepted friend rows require that ID. Missing IDs are contract errors,
not a reason to substitute the user's ID. Authorization remains on the backend.

The profile offers actions for no relationship, outgoing/incoming requests and accepted
friends. Mutations refresh both people and friends queries even on failure, since another
tab may have changed the relationship or a response may have been lost after commit.
Friend-list mutations optimistically hide a row, restore it on failure, and reconcile it
with the server. Removal requires confirmation, and errors stay inside the open dialog.

## Repeatable integration test

Use the disposable loopback database and capture-mail harness in
[auth-screens.md](auth-screens.md#automated-and-browser-checks). From `frontend`, set
`WOZU_TEST_BACKEND_URL=http://127.0.0.1:8010` and run:

```sh
npx vitest run --config scripts/auth-backend.config.ts
```

The config includes `social-backend.integration.ts` alongside the existing authentication,
account and profile journeys. It registers two disposable people and tests profile privacy,
send/conflict, incoming requests, decline, reversed request, accept, a fresh sign-in,
relationship IDs after reloading data, removal on both sides, and conversation reuse.
CI runs it against the actual backend. The harness captures mail and must never be deployed.
The test leaves disposable records in its explicitly named test database.

## Browser evidence — November 13, 2026

On the integrated local frontend and merged BE-22 backend: signed in, opened an incoming
request's public profile, accepted it, reloaded and saw Remove friend, found it in Friends,
cancelled removal (friend retained), confirmed removal (empty state), reopened the profile
and sent a new request. Message reached the backend-created `/chat/{id}` route. That route
currently contains Ahmad's placeholder; implementing the chat thread is outside these cards.

Checked the desktop profile and 360-pixel friends layout, including the confirmation dialog;
the mobile document had no horizontal overflow. Cancellation restored focus to the removal
button. The checked normal-flow tab had no captured browser warnings/errors. This is local
HTTP evidence, not a new production HTTPS test. Screenshots are in the dated review evidence.

English fallback remains until FE-07; online status is a snapshot until FE-12. Cross-pair
review, ordered parent merges and the owner's live-change exercise remain completion gates.
