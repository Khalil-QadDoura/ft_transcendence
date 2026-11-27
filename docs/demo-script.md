# QA-03 module demonstration script

Owner/facilitator: Zayid Elkahir. [Card](https://trello.com/c/7WYLKAxw).
Prepared November 26, 2026 against main `18ae950`; module inventory: DOC-06 #104.
This is a run sheet, not evidence of a completed timed rehearsal. Owners must
check their rows against the final merged revision. College time allowance is
not yet confirmed; the proposed core below is 25 minutes plus questions.

## Before the audience arrives

1. Record `git rev-parse HEAD`, browser versions and the date in the rehearsal
   record. Use the reviewed defense checkout, not an unmerged personal branch.
2. On the disposable defense stack follow README prerequisites, run `make`, then
   `make seed`. Do not run `make reset-demo`, `make re`, or `make fclean` on a
   populated shared stack. Record failures instead of silently skipping them.
3. Open the site at the HTTPS address printed by `make`. Use separate browser
   profiles for candidate1, candidate2 and employer1. Seeded accounts are
   `candidate1@wozu.demo`, `candidate2@wozu.demo`, `employer1@wozu.demo`; the public,
   demo-only password is `WozuDemo2026!`. Never use these for production accounts.
4. Open `/mail/`, `/status`, and `/grafana/` in advance. Grafana's actual generated
   credentials stay private; do not put them in screenshots or this document.
5. Confirm OAuth keys, callback URL and moderation key only with the responsible
   owner. Missing external credentials are a limitation, not a reason to fake
   success. Seeded approved clips demonstrate playback, not a new moderation run.
6. Choose one seeded job from the visible search results; use its actual link,
   not a hard-coded numeric ID. Open candidate2's public profile from Friends.

## Core run: proposed 25-minute budget

| Minutes | Presenter / modules | Actions and expected result | Failure/fallback |
| --- | --- | --- | --- |
| 0–2 | Burhan + Khalil, M1/M5 | Show healthy `docker compose ps`, README architecture and database diagram. Trace browser → HTTPS proxy → API → ORM/database. Explain React/Vite and FastAPI ownership. | Use the same revision's diagram to explain a fault, but record startup failure; a diagram does not replace a working stack. |
| 2–6 | Zayid + Khalil, M4/M15 | Register a new disposable account, follow its Mailpit verification link, log in, edit `/profile`, upload an allowed avatar, and reload. Show default avatar on an account without one. On `/friends`, show candidate2's profile and online state in the second session. Demonstrate 42 login only when configured. | Wrong password must show a recoverable error; unverified login must remain blocked. If OAuth lacks keys, state M15 could not be demonstrated; do not substitute a normal login. |
| 6–9 | Ahmad + Nader + Zayid, M6 | At `/jobs`, change keyword, salary and location filters, change sort and load another page when available. Switch to employer1 at `/employer/jobs`, create a clearly named disposable draft, edit it and publish it; refresh search to show it. | Show an empty search as a legitimate state. If create fails, preserve values and show the error. Never edit/delete a teammate's real job. |
| 9–12 | Ahmad + Khalil + Nader, M9 | At `/videos`, play a seeded approved clip; then record/upload a new short clip and observe pending → approved/rejected/moderation_error with the worker running. Explain presigned storage, validation and why unapproved clips cannot be posted. | If provider unavailable, show the genuine failure state and retry path. A seeded clip does not prove the moderation provider ran. |
| 12–15 | Ahmad + Nader + Khalil, M2/M3 | Open the same direct chat in candidate1/candidate2 profiles. Send a uniquely named message and observe live delivery, then edit/delete your own message. Reload and show persisted history. Disconnect/reconnect one browser and verify recovery without duplicate sends. | If the socket fails, show the connection state and diagnose; polling/history alone is not evidence of live WebSockets. |
| 15–18 | Zayid, M10/M11 only after #93 merges | Switch English → Arabic → Russian at `/profile`, `/jobs`, `/employer/jobs`, `/privacy` and `/terms`. Show mirrored navigation, correct mixed-text ordering, translated validation with preserved input, legal original toggle and reload preference. | Legal translations retain their pending-review notice until actually reviewed. Main without #93 does not demonstrate completed M10/M11. Browser preference is the accepted defense scope; no account persistence claim. |
| 18–23 | Burhan + Nader, M12/M14 | Open `/status` and Grafana's API/infrastructure dashboards. Show metrics, five alert rules and the protected dashboard. On the disposable demo stack only, run `make alert-demo`; show firing then resolved alert. Show `make backup-list` and the recovery runbook. | If alert latency exceeds the slot, show the actual current state and continue timing. Restore requires a separate disposable rehearsal and evidence; never restore the audience's/shared data just to save time. |
| 23–25 | Zayid, M16 only after FE-16 evidence | Repeat a compact login/profile/language/chat smoke on Firefox and Edge. Point to the full flow-by-browser results, versions and limitations. | A Chrome-only test or screenshots are not two additional browsers. Until the matrix is actually completed, keep M16 unclaimed. |

## Conditional modules and mandatory feature follow-up

These segments must be rehearsed and inserted before claiming the corresponding
modules. Reallocate time with the PO after the college confirms the limit.

| Owner | Dependency | Live steps after merge | Expected result / failure rule |
| --- | --- | --- | --- |
| Ahmad + Nader | Apply UI #47 and employer review #99 | Candidate opens an actual job detail link, selects an approved clip, submits once; employer reviews it and changes status; candidate sees it in `/applications`. | Duplicate submission is handled, only the job owner sees applicants, status persists. Existing seeded applications alone do not prove apply works. |
| Ahmad + Khalil + Nader | Game room #86, restore #88, connection #98; M7/M8/M18 | Three human sessions join from `/game`; open assigned rooms, discuss, vote and inspect results. Reload one session, reconnect within the grace period and compare all clients. | Server owns phase/score, no hidden bot identity before results, clients agree, reconnect restores the same seat. Lobby-only navigation does not prove a playable game. |
| Burhan | WAF #94 + Vault secret consumption #103; M13 | Follow the reviewed WAF smoke test to show a benign request succeeds and an attack fixture is blocked. Demonstrate a service reading only its allowed Vault path, with secrets redacted. | DetectionOnly is not blocking; a running Vault with services still using `.env` is not completed secret integration. |

Optional Tier C modules are not included or counted. Check README points against
the final merged revision; do not count pending PRs or promise evaluation points.

## Owner sign-off and timed run

| Owner | Rows checked at commit | Corrections / PR link | Confirmed |
| --- | --- | --- | --- |
| Zayid | Pending final integration | Frontend, languages, browsers, facilitation | Pending |
| Khalil | Pending | Auth/security, storage contracts, game | Pending |
| Nader | Pending | Search, messaging, moderation, health, seed, game | Pending |
| Ahmad | Pending | Shared clients and feature screens | Pending |
| Burhan | Pending | Infrastructure, legal/module claims, timing | Pending |

Record the actual elapsed time, failures and resolution links in the QA-04
rehearsal record. QA-03 closes only after owner review and a timed run that fits
the confirmed allowance, not when this proposed schedule is written.
