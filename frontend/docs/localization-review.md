# FE-07 / FE-08: translation and Arabic layout review

Owner: Zayid Elkahir. Sprint 3, due November 24, 2026 at 18:00 Abu Dhabi.
[FE-07](https://trello.com/c/Dqc62LOP) · [FE-08](https://trello.com/c/g4MC9MRU).

## Implementation

English, Arabic, Azerbaijani, Turkish and Russian now have every shipped interface namespace. This includes auth, account settings, profile, people, jobs, applications, video, chat, the legal-page shell, common controls, status and game rules. Employer and friends resources include the keys needed by pending PRs #91 and #90; their screens are not part of this branch. Routes still marked Coming Soon on main remain placeholders.

`src/i18n/index.ts` discovers each locale's JSON resources. `useTranslation` subscribes components to language changes. Existing auth/account copy helpers resolve translations at render time through `translatedCopy`; form values and session state survive switching. Known persisted UI errors are retranslated by `localizeMessage`. General jobs/chat/media failures use translated recovery messages; arbitrary backend validation details on profile/auth are preserved, not falsely described as fully translated. API error-code coverage needs to grow with backend contracts.

`Intl` formats dates, numbers and salaries using the selected language. Count messages use i18next plural categories, including Arabic zero/one/two/few/many/other and Russian one/few/many/other. English fallback remains a runtime safety net, not an exemption from the catalog check.

`npm run i18n:check` rejects missing keys, missing required plural forms, unknown keys, blank values and interpolation mismatches in all four target locales. A separate JSX scan rejects untranslated production literals. Neither check proves linguistic quality or discovers all computed/server-provided text.

## Arabic behavior

Switching Arabic sets `html.lang=ar` and `html.dir=rtl` without navigation. Logical spacing, borders and positions follow direction; directional arrows mirror. Arabic typography has readable line height and no Latin tracking. Shell content wraps on mobile. Text fields use `dir=auto`; email, password, URL and numeric controls retain LTR order. Mixed names and job titles use bidirectional isolation. Tabs use visual arrow direction, skip disabled items and retain Home/End behavior.

## Verification on November 22

- Full frontend suite: 274 tests passed after the final persisted-error, tab-direction and localized relative-time changes.
- Typecheck, lint, strict catalog checks, formatting, legal synchronization and production build passed. The existing large-bundle warning remains; eager language resources increase the bundle.
- Live auth integration against the disposable main backend: all 3 tests passed (registration/verification/session and password lifecycle exercised by the existing harness).
- Browser: all five homepage languages at 360px had no horizontal document overflow. Arabic desktop home, mobile profile/settings, sign-in failure, switch to Russian with the existing error, successful sign-in, and mixed Arabic/English direct-chat sending were checked against the local backend.
- Screenshots below use disposable fixtures. They do not establish a complete cross-browser or every-screen audit; FE-16 owns additional browsers. Game rooms, employer pages and friends pages need a follow-up after their pending implementations land.

![Arabic homepage at desktop width](evidence/fe07-fe08/arabic-home-desktop.jpg)
![Arabic profile at mobile width](evidence/fe07-fe08/arabic-profile-mobile.jpg)
![Mixed Arabic and English chat](evidence/fe07-fe08/arabic-chat-desktop.jpg)

## November 23 review follow-up

Merged main at 1ca48d6 into the PR and addressed Khalil's changes-requested review:

- Added all nine 42 OAuth messages in all five languages, updated the gateway mock and mirrored OAuth arrows. Removed the three obsolete feature copy files so later changes cannot silently bypass the catalogs.
- Restored the explicit temporary company/game English fallback requested by Khalil, until code freeze (November 26). This exception is limited to those newly landed namespaces; the strict checker still validates all other catalogs. Do not claim the whole module is accepted while these remain incomplete.
- Fixed empty Arabic input/textarea placeholder direction without reversing typed Latin text. Job descriptions now use automatic direction.
- Added a deterministic Azerbaijani formatting catalog because Chromium can lack date/relative-time data even when Node has it.
- Mapped both known password/reset backend error texts to translated messages.
- Added complete reading translations of Privacy and Terms in AR/AZ/TR/RU. The legal body and table of contents follow the chosen language; Arabic uses RTL. A localized review-pending notice and English-original toggle remain visible. Canonical source hashes, dates, structural coverage and packaged-copy drift are checked by legal:check. Translation date is distinct from source policy dates.
- Removed the old jobs-search blocker: BE-26 /api/jobs/open is now on main. This update does not claim a new live job-search test.

## Acceptance still pending

1. Fluent speakers/content owner must review the new translations. The legal texts are now implemented, but approval is not implied by structural tests. Record actual reviewers below. Hide incomplete languages at code freeze as the card requires.
2. Account persistence remains local until the backend contract is agreed and implemented. See [the proposal sent to Khalil](language-preference-contract.md). No unsupported PATCH calls were added.
3. Company/game catalogs are temporarily English-only under Khalil's requested exception. Pending game/employer/friends implementations need their own final RTL pass after they land.
4. Fresh browser verification of this November 23 update could not run because the browser-control service timed out. The images above are November 22 evidence, not new legal-page screenshots. Automated render/direction/navigation tests cover every legal locale; visual approval is still pending.
5. Khalil's fresh review and current-head green CI are merge gates. These cards are not Done.

| Language    | Fluent reviewer | Status  |
| ----------- | --------------- | ------- |
| Arabic      | Unassigned      | Pending |
| Azerbaijani | Unassigned      | Pending |
| Turkish     | Unassigned      | Pending |
| Russian     | Unassigned      | Pending |

## Adding or changing copy

Add the English key and its four translations together. Preserve interpolation names; use whole sentences rather than assembling translated fragments. Subscribe the component to the namespace. For counts, pass `count` and provide every locale-required plural category. Keep backend enums, identifiers and payload field names unchanged. User-generated content is not translated. Run catalog checks, the affected feature tests, typecheck and lint, then inspect both LTR and RTL layouts. Record reviewer/date here after a real language review.

Study exercise: change one Arabic validation message, cause that error, switch to Russian without clearing the form and explain why the error changes but the input value does not. In a practice branch, remove a Russian plural form and verify the catalog check fails.
