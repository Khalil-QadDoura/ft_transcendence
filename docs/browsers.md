# FE-16 browser verification

Owner: Zayid Elkahir. [Card](https://trello.com/c/gVJxTGO4).
Updated November 26, 2026. Status: in progress, not a completed M16 claim.

## Verified fix: game-rules document overflow

Khalil reported `/game/rules` overflow on mobile in the #93 review. Reproduced
against the production build of #93 at `1fec709` in the in-app Chromium browser,
viewport 360 × 800 (layout viewport 345px after the scrollbar). English document
width was 454px and Arabic 426px, although the table containers themselves had
horizontal scrolling. Absolutely positioned screen-reader descriptions inside
the table lacked a positioned containing block inside that scroll container.

Adding `relative` to both existing `overflow-x-auto` regions confines their
descendants without hiding accessible text or changing game scoring. With this
two-line patch, EN/AR/AZ/TR/RU document width equals the 345px layout viewport;
the large table still scrolls inside its 239px region (576px content). The ten
game-rules component tests and production build pass on the integrated #93
source. No captured warning/error messages were returned for this rules-page
pass. This is not an authenticated backend or whole-site console audit.

The fix is submitted independently against main. Five-language measurements use
the #93 integration build, because full language catalogs have not merged yet.
No browser version was captured in this pass, so it is not counted as the formal
versioned compatibility matrix below. The in-app browser is not Firefox or Edge.

## Required final matrix

Record exact stable versions, OS, commit and date. Use a production build served
with the real backend. Every row must pass in **Firefox and Edge** in addition
to the primary Chromium baseline; a different Chromium tab is not another browser.

| Flow | Firefox version/result | Edge version/result | Dependencies / evidence needed |
| --- | --- | --- | --- |
| Register, verify, login, logout, reset | Not run | Not run | Disposable account; actual Mailpit flow |
| Profile edit and avatar | Not run | Not run | Save/reload, invalid upload, default avatar |
| Video recording, upload, playback | Not run | Not run | Camera permission, supported codec, real upload/moderation |
| Jobs/search/map filters | Not run | Not run | Real API results, paging and empty/error states |
| Apply and employer review | Not run | Not run | #47/#99 still pending at this snapshot |
| Chat/presence/reconnect | Not run | Not run | Two independent sessions, no duplicates |
| Multiplayer game | Not run | Not run | #86/#88/#98 still pending at this snapshot |
| Five languages and Arabic mirroring | Partial Chromium rules-page only | Not run | #93 approval/merge, all main routes |
| Legal/status and responsive layout | Not run | Not run | Translation notices, original toggle, actual health endpoint |

The connected browser inventory currently exposes only the in-app browser; no
Firefox/Edge browser session is available. Their full verification remains open.
Do not mark FE-16 Done until both additional browsers have actual results and any
limitations are documented in README. Keep newly merged game/apply routes in the
matrix rather than treating Coming Soon pages as passed features.

## FE-17 production console follow-up

At the final revision, visit `/`, `/jobs`, `/login`, `/register`, `/verify-email`,
`/forgot-password`, `/reset-password`, `/oauth/callback`, `/profile`, `/settings`,
`/friends`, `/users/:id`, `/company`, `/videos`, `/applications`, `/employer/jobs`,
the employer create/edit routes, `/chat`, `/chat/:id`, `/game`, `/game/rules`,
`/privacy`, `/terms`, `/status` and the 404 route. Add pending routes after merge.
Use real IDs from links. Record route/action, warning/error text, source and owner.
Check navigation/reconnect, stale session, validation, failed uploads and empty
states. Do not silence console methods or suppress real failed requests to obtain
a clean result. The current preview has no connected backend and displays the
session-recovery failure correctly; it cannot certify FE-17's real-flow criterion.
