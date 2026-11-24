# ft\_transcendence — Overview & Plan

Oct 27, 2026 · updated Nov 4, 2026 · @byul-byul

## TL;DR

We build **WOZU Web**: a job platform where candidates apply with a short video instead of a CV, talk to employers in real-time chat, and play a social-deduction mini-game ("Turing Duel"). The WOZU backend is our reference; we write a new backend and a web frontend on top of it.

- **Target:** 14 mandatory points + 5 bonus = 19, the maximum that counts. We plan 26 points (core 19 + tier B 5 + Remote players 2) so that one or two modules can fail at the defense without losing the maximum.
- **Good news:** the reference backend already covers most of the 19 core points. I ran it: all 36 migrations apply on a clean database and all 127 tests pass.
- **Real work:** a web frontend from scratch, HTTPS for everything (including file uploads), Privacy Policy and Terms of Service pages, and fixing about 20 issues we must not copy.

**Decided on 2026-11-04** (entries in the decisions log):

1. Roles: byul-byul PO + DevOps; Khalil Tech Lead + Backend A; Nader Backend B; Zayid PM / Scrum Master + Frontend A; Ahmad Frontend B.
2. Modules: core 19 (M1–M12) + tier B 5 (M13–M16) + M18 Remote players; tier C (M17, M19, M20) stays in Backlog.
3. Stack: React + TypeScript + Vite + Tailwind, FastAPI, PostgreSQL + PostGIS, Redis, nginx + ModSecurity CRS (see Stack).
4. The Turing Duel game stays; its rules are in "Turing Duel rules".
5. Dates: four sprints from Nov 4 to Nov 28, code freeze Nov 26, first defense Sunday Nov 29.

Work is planned and tracked on the [Trello board](https://trello.com/b/E3788fBx/fttranscendence): how it works in [board.md](board.md), the card list in [backlog.md](backlog.md).

## What the reference gives us

The reference is a working, tested FastAPI backend: 76 HTTP endpoints, 2 WebSocket endpoints, 25 tables, 127 passing tests. Verified on 2026-10-27 by running migrations and the full test suite against PostgreSQL 16 + PostGIS and Redis.

| Area | What exists | Ready for ft? |
| --- | --- | --- |
| Auth | Email + password, Argon2id hashing, email verification, JWT access + refresh rotation, logout, change / forgot / reset password, rate limits | Yes; verification depends on the Brevo email API |
| Users & profiles | Own profile (read, edit, soft delete), public profile with online status, avatar upload | Mostly; no way to display an avatar, no default avatar |
| Friends | Request, accept, decline, remove, list with online status | Yes |
| Chat | Conversations with participants, unread counters, read receipts, edit / delete, idempotent send; WebSocket push via Redis pub/sub | Yes; a second legacy chat system should be dropped |
| Jobs | CRUD, filters (geo radius, salary, schedule, urgency, full-text keyword), sort newest / nearest, cursor pagination | Yes |
| Applications | Apply with video, status state machine with event log, employer view | Yes, two status bugs |
| Video resumes | Upload to MinIO via presigned URL, async moderation (ffmpeg + Whisper + OpenAI moderation) in a Celery worker, feed | Not from a browser yet: MinIO is not reachable over HTTPS |
| Turing Duel game | Matchmaking queue, rooms of 2 to 5 with bot fillers, timed discussion and voting phases, scoring, results | Backend only; bot is template-based; no reconnect support |
| Infra | Docker Compose with Caddy (automatic TLS), API, Celery worker, Postgres + PostGIS, Redis, MinIO; health endpoint | Partly; frontend, MinIO over TLS and monitoring missing |

Details, the database schema and the list of issues are in the Backend Reference doc.

## Mandatory part checklist

Any miss here rejects the whole project, whatever the module score. The reference covers secure auth, password hashing and env handling; the frontend, HTTPS for uploads, legal pages and a clean schema are on us.

| Requirement | Reference today | What we must do | Track |
| --- | --- | --- | --- |
| Web app: frontend + backend + database | Backend + PostgreSQL only | Build the web frontend | FE |
| Privacy Policy and Terms of Service, linked from the footer, real content | Missing | Write content specific to video resumes, OpenAI processing, retention; render pages | PO + FE |
| Every browser connection over HTTPS | API yes (Caddy); file uploads go to MinIO over plain HTTP on an internal host | Serve frontend, API, WebSocket and MinIO through the nginx front proxy over TLS (INF-03, INF-04) | Infra |
| Chrome, no console errors or warnings | n/a | Avoid expected 4xx responses in normal flows (Chrome logs them as errors), clean React warnings | FE + BE |
| Responsive, accessible frontend with a CSS framework | n/a | Tailwind, mobile-first layouts | FE |
| Forms validated on frontend and backend | Backend validates with Pydantic; avatar extension and object key not validated | Mirror rules in frontend forms; close backend gaps | FE + BE |
| Sign up and log in securely, hashed + salted passwords | Yes (Argon2id) | Keep; make email verification work without a paid email service | BE + Infra |
| Database with a clear schema and relations | Works, but 36 migrations carry legacy tables, two chat systems, unused columns | Start the new backend with a clean schema and a fresh migration history | BE |
| Multiple users at once, no race conditions | Mostly; game matchmaking would race with more than one API worker | One worker or a Redis lock on the matchmaking tick | BE |
| One-command deployment with containers | `docker compose up -d` (backend only) | Root compose file including the frontend; `make` wrapper | Infra |
| `.env` ignored by Git + `.env.example` | Yes | Keep, extend for new services | Infra |
| Git: commits from all members, clear messages | n/a for the new repo | Conventions below; never import the reference as one big commit | All |
| README with all required sections | One-line README | PO owns it; every member writes their part (DOC-03 … DOC-07) | All |
| Team roles documented | Not yet | Roles decided 2026-11-04 (see Roles); list them in the README | PO |

## Roles

Decided 2026-11-04: the three lead roles are spread across the three tracks, so each sub-team has a lead and every member has a visible responsibility to explain at the defense. The subject allows combined roles in any team size.

| Person | Track | Role(s) | Main responsibilities |
| --- | --- | --- | --- |
| byul-byul | Infrastructure | Product Owner + Developer (DevOps) | Product vision (knows WOZU best), backlog priorities, accepts finished cards, README and legal pages content; Docker, nginx + ModSecurity / TLS, monitoring, security modules |
| Khalil | Backend | Tech Lead / Architect + Developer (Backend A) | Backend architecture and API contract, stack decisions, reviews critical PRs, code quality rules |
| Nader | Backend | Developer (Backend B) | Ports and owns backend modules (see Work split) |
| Zayid | Frontend | PM / Scrum Master + Developer (Frontend A) | Runs the Trello board, weekly sync, tracks deadlines and blockers, keeps the risk list |
| Ahmad | Frontend | Developer (Frontend B) | Owns frontend modules (see Work split) |

The alternative from the first draft (byul-byul as Tech Lead + DevOps, a frontend dev as PO) was not taken.

Whatever the split, each member must be able to explain the whole project and make a small code change during the defense.

## Module plan

Decided 2026-11-04: core set = 19 points, built mostly on what the reference already does; buffer tier B adds 5 more and M18 Remote players 2 more, for a planned 26. A module counts only if it fully works at the defense, so the buffer is insurance, not extra credit. The M-numbers are the module labels on the Trello board ([board.md](board.md#labels)).

**Core (19 points)**

| Label | Module | Type | Pts | Reference today | Main work for us | Track |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | Frameworks for frontend and backend | Major | 2 | FastAPI | React frontend | FE + BE |
| M2 | Real-time features (WebSockets) | Major | 2 | `/ws` with Redis pub/sub | Client reconnect, broadcast edits / deletes, presence in Redis | BE + FE |
| M3 | User interaction: chat, profile, friends | Major | 2 | All three exist | Chat, profile and friends UI | FE |
| M4 | Standard user management | Major | 2 | Profile edit, avatar upload, friends + online status | Avatar display URL, default avatar, profile page | BE + FE |
| M5 | ORM | Minor | 1 | SQLAlchemy 2 async + Alembic | Keep | BE |
| M6 | Advanced search: filters, sorting, pagination | Minor | 1 | Job search with geo, salary, schedule, keyword, sort, cursor | Search UI with filters and paging | FE |
| M7 | Web-based game | Major | 2 | Turing Duel backend | Game UI, clear win / loss result, room history endpoint | BE + FE |
| M8 | Multiplayer game, 3+ players | Major | 2 | Rooms of 2 to 5 | Rooms of up to 5 participants per the Turing Duel rules, state sync for all clients | BE + FE |
| M9 | Content moderation AI | Minor | 1 | Video moderation with Whisper + OpenAI moderation | Fix the `moderation_error` enum bug; demo both approve and reject | BE |
| M10 | Multiple languages (3+) | Minor | 1 | WOZU app had EN / AR / ID / TR | i18n with AR, EN, AZ, TR, RU, language switcher | FE |
| M11 | Right-to-left language support | Minor | 1 | Arabic already in the language set | Full layout mirroring for AR | FE |
| M12 | Monitoring with Prometheus + Grafana | Major | 2 | Structured JSON logs, health endpoint | Metrics, exporters, dashboards, alerts, secured Grafana | Infra |

**Buffer tier B (+5)**

| Label | Module | Type | Pts | Why it is cheap | Track |
| --- | --- | --- | --- | --- | --- |
| M13 | WAF / ModSecurity + HashiCorp Vault | Major | 2 | Pure infrastructure, no app redesign | Infra |
| M14 | Health check, status page, automated backups, recovery | Minor | 1 | Health endpoint exists; add `pg_dump` schedule and a restore runbook | Infra |
| M15 | OAuth 2.0 (42 intra) | Minor | 1 | One login flow on top of the existing token issuing | BE + FE |
| M16 | Additional browsers (Firefox, Safari or Edge) | Minor | 1 | Test and fix, document limits | FE |

**Added on 2026-11-04 (+2, planned total 26)**

| Label | Module | Type | Pts | Main work for us | Track |
| --- | --- | --- | --- | --- | --- |
| M18 | Remote players | Major | 2 | Reconnect and room resync (BE-09, FE-33), seat grace period and peer connection status on disconnect (BE-33, FE-36) | BE + FE |

**Tier C (Backlog, no due date; start only if core + tier B are on track on Nov 22):** M17 AI Opponent (Major, 2; TC-01) needs the bot rewritten, today it sends random template lines and a careful evaluator may reject it; M19 GDPR features (Minor, 1; TC-02, TC-03) fit the Privacy Policy; M20 Organization system (Major, 2; TC-04, TC-05) would bring back WOZU company teams.

**Point math:** core 19 = 7 Majors (14) + 5 Minors (5). Tier B: 1 Major + 3 Minors = 5. M18: 1 Major = 2. Planned total 26. If two core minors fail, tier B still keeps us at 19+.

## Stack

Decided 2026-11-04.

| Layer | Choice |
| --- | --- |
| Frontend | React + TypeScript + Vite + Tailwind; React Router, TanStack Query, react-i18next, native WebSocket |
| Backend | FastAPI |
| Data | PostgreSQL + PostGIS, Redis |
| Files and mail | MinIO at `/files`, Mailpit at `/mail` |
| Moderation worker | Celery (OpenAI + Whisper) |
| Front proxy | nginx + ModSecurity CRS (decided in INF-01) |
| Secrets | HashiCorp Vault |
| Monitoring | Prometheus + Grafana |
| Languages | AR, EN, AZ, TR, RU (M10); RTL on AR (M11) |

## Turing Duel rules (decided 2026-11-04)

Decided by byul-byul on 2026-11-04. These rules are the input for card DOC-08, which produces the final player-facing rules; BE-10 and FE-34 depend on DOC-08.

**Lobby and room**

- A room holds up to 5 participants, at least 1 of them human.
- When a room is created, the server secretly and randomly decides whether this room gets bots at all, and if so how many (1–4). Bots join one at a time with random delays (e.g. 10–30 s, configurable), interleaved with humans who join meanwhile. The total never exceeds 5: planned bots that no longer fit are not added. Some rooms get no bots at all.
- Participants are anonymous in the game: shown only as "Player 1…N" (stable per room), no name, no avatar, no profile link. Bots need no fake profiles. Nothing in the API, WebSocket events or UI may reveal which participants are bots, or whether the room has any; results come only after the game ends.
- A single 3-minute timer starts when the room is created and never restarts.
- The game starts as soon as one of these happens: the 5th participant joins; a human presses "Start now" (shown while the room has 2–4 participants; first press wins, later presses ignored via server-side lock); the timer expires with 2 or more participants.
- If the timer expires with only 1 participant, the room closes and the human returns to the lobby to start a new room.
- All participant counts include bots (counting only humans would leak bot presence). Planned bots that have not joined when the game starts are not added.

**Scoring**

- Each human marks every other participant as bot or human: every mark starts at "human" and can be changed until voting ends; +1 correct, −1 wrong, and a mark left at "human" counts (no "no guess" since 2026-11-15).
- Highest score wins; a shared top score is a draw.
- Room with a single human (1 human + bots): score above 0 is a win, 0 a draw, below 0 a loss.
- A disconnected player keeps the marks they had, still counts as one of the humans for who wins, and gets a score and an outcome. Full rules: [game/turing-duel-rules.md](../game/turing-duel-rules.md).

## Work split

Each person owns whole modules end to end inside their track, so the README can name one owner per module and the Git history backs it up. Pairs split by domain, not by layer. The split below follows card ownership on the board (2026-11-04); the full list per owner is in [backlog.md](backlog.md).

| Person | Owns (cards; modules) | Shared / cross-track |
| --- | --- | --- |
| Khalil (Tech Lead, Backend A) | Skeleton, initial migration (BE-01, BE-02; M1, M5), auth and password flows (BE-03, BE-04), `/users/me`, avatar and logo (BE-05, BE-08; M4), WebSocket layer + presence (BE-06; M2), intro video upload and feed (BE-07; M9), game WebSocket, history, votes and results (BE-09, BE-10; M7, M8, M18), OAuth 42 (BE-11; M15), rate limits (BE-12), backend security review (BE-13), schema diagram (BE-14); tier C: TC-01 (M17), TC-02 (M19) | API contract; game backend with Nader |
| Nader (Backend B) | Test infrastructure (BE-20), companies (BE-21), friends + public profile (BE-22; M3, M4), conversations + messages (BE-23, BE-24; M3, M2), jobs CRUD + search (BE-25, BE-26; M6), matchmaking and rooms (BE-27; M7, M8), applications (BE-28), moderation worker (BE-29; M9), `/metrics` and `/api/health` (BE-30, BE-31; M12, M14), seed script (BE-32), game disconnects (BE-33; M18), multi-user concurrency test (QA-02); tier C: TC-04 (M20) | Frontend help: company profile form (FE-14), game lobby (FE-31) |
| Zayid (PM, Frontend A) | How we work + sprint routine (PM-00, PM-01), scaffold, app shell, form validation, auth and password screens (FE-01 … FE-05), i18n, translations, RTL (FE-06 … FE-08; M10, M11), profile, public profile, friends (FE-09 … FE-11; M3, M4), legal pages (FE-13), employer job pages (FE-27), additional browsers (FE-16; M16), console-clean pass (FE-17), README Project Management and contributions (DOC-04, DOC-07), demo script and walkthroughs (QA-03, QA-04); tier C: TC-03 (M19) | — |
| Ahmad (Frontend B) | API client (FE-20; M1), UI components on design tokens (FE-21), WebSocket client (FE-22; M2), online status (FE-12), jobs search, job detail + apply (FE-23, FE-24; M6), video recording + "My videos" (FE-25, FE-26; M9), "My applications" and employer applications view (FE-15, FE-28), chat list + thread (FE-29, FE-30; M3), game room, restore and connection state (FE-32, FE-33, FE-36; M7, M8, M18), accessibility and responsive pass (FE-35); tier C: TC-05 (M20) | — |
| byul-byul (PO + DevOps) | Front proxy decision, repo layout, compose, Makefile, one HTTPS origin, MinIO at `/files`, Mailpit, CI, pinned images and health checks (INF-01 … INF-07), Prometheus + Grafana + alerts (INF-08 … INF-10; M12), WAF + Vault (INF-11 … INF-13; M13), backups, restore runbook, status page (INF-14 … INF-16; M14), clean-machine rehearsal (QA-01) | Privacy Policy and ToS content (DOC-01, DOC-02), README (DOC-03, DOC-05, DOC-06), Turing Duel rules (DOC-08) and rules page (FE-34), backlog |

The frontend is the critical path: both frontend devs start on day one against the API contract and the reference backend running locally (it works today), not waiting for the new backend. Nader and byul-byul take three frontend cards (FE-14, FE-31, FE-34).

## Defense risks

The biggest risks are environment ones, not code: email, OpenAI and HTTPS uploads each depend on setup that must work on the evaluator's machine.

| Risk | Effect at defense | Fix | Owner |
| --- | --- | --- | --- |
| Email verification needs a Brevo API key; without it the link only goes to the server log | Evaluator cannot finish sign-up | Mailpit container (local mail catcher with a web inbox) + SMTP sender; links point to frontend pages | Infra + BE |
| Uploads go to `minio:9000` over HTTP | Avatar and video upload fail in the browser; HTTPS rule broken | MinIO behind nginx TLS at `/files` on the same origin, no CORS needed (INF-04); backend checks the object exists on confirm | Infra + BE |
| Moderation needs a funded OpenAI key; on API errors it approves everything | Moderation module looks like it does nothing | Real key in `.env` on defense day; demo one approved and one rejected video | BE |
| Chrome logs every 4xx response as a console error | "No console errors" fails, e.g. `GET /companies/me` returns 404 for job seekers | Normal flows return 200 with empty data; refresh tokens before expiry | BE + FE |
| Self-signed certificate on localhost | One browser warning; WebSocket fails if served from another origin | Serve frontend, `/api` and `/ws` from one origin through nginx (INF-03) | Infra |
| Matchmaking loop runs in every API worker | Duplicate rooms under load | Keep one worker or take a Redis lock per tick | BE |
| Template bot | AI Opponent claim rejected | Do not claim AI Opponent unless the bot is rewritten (tier C, TC-01) | BE |
| Big import commits, one person's code | Git history shows poor work distribution | Port the reference module by module, one card and one PR each, owner commits | All |
| A member cannot explain another part | Live code-change request fails | Code reviews across pairs; a 30-minute walkthrough per module before the defense | PM |

The final player-facing and implementation rules are maintained in [Turing Duel rules](../game/turing-duel-rules.md) (DOC-08, merged). The November 4 decisions above remain historical input; use that canonical document for exact timings, labels and scoring.

## Ways of working

Every change travels card → branch → PR → review → merge → card moved, so the [Trello board](https://trello.com/b/E3788fBx/fttranscendence) and the Git history tell the same story at the defense. The board in detail: [board.md](board.md).

**Trello board**

- Lists: Backlog → To Do (= current sprint) → In Progress → Review → Done. One-week sprints (S1 Nov 4–10, S2 Nov 11–17, S3 Nov 18–24, S4 Nov 25–28); byul-byul (PO) orders Backlog, Zayid (PM) runs To Do.
- Labels: track (`Backend`, `Frontend`, `DevOps`, `Docs`), secondary (`Security`, `Database`), module (`M1` … `M20`), `Mandatory`, priority (`P1`, `P2`), `Bug`. Colors and meanings in [board.md](board.md#labels).
- One owner per card, named on the `Owner:` line and matching the Trello member on the card; a reviewer from the other pair reviews the PR when the card reaches Review.
- PM-01 connects the GitHub Power-Up to show PRs and commits on cards. November 8 status: enabled, repository authorization/linking still pending.

**Card format**

```markdown
Title: <CARD-ID> <verb> <what> — e.g. "BE-08 Port avatar and logo upload with checks; return avatar_url and logo_url"

Owner: <name>
Why: one line linking to the module or mandatory item
Done when:
- [ ] acceptance criterion 1
- [ ] acceptance criterion 2
- [ ] tests added / updated
- [ ] API contract doc updated (if the API changed)
- [ ] Definition of Done met (PM-00)
Depends on: <CARD-ID>
```

**Git**

- Merge policy: use a PR with one approving review and a green `ci-ok` check, the gate job of the single CI workflow `ci.yml` (INF-06; jobs and branch protection settings in the Infrastructure doc, section "CI"). Branch protection on `main` enforces both once the repo admin applies it.
- Branch name: `<type>/<CARD-ID>-<short-name>`, e.g. `feat/BE-07-intro-video`, `fix/BE-10-vote-room-check`.
- Commit message: `<type>(<scope>): <summary> (<CARD-ID>)`, types `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`. Example: `feat(game): reject votes for participants of other rooms (BE-10)`.
- Small PRs (under \~400 changed lines), one card each. Squash merge keeps one clear commit per card on `main`.
- Everyone commits their own work from their own account; pair work uses `Co-authored-by:` lines.
- Weekly sync (30 min, PM leads) + async daily update in the team chat: done, next, blocked. Proposed slots and outstanding confirmations are tracked in [sprint-routine.md](sprint-routine.md).
- Review and live-change rule, set by the PO on 2026-11-08: every PR receives a review within 24 hours from someone in the other pair. After each merge, the owner makes one small live change and records what changed and how it was checked.

## Related documents and decisions

- [Sprint routine](sprint-routine.md): weekly sync, daily update, open team agreements (PM-01).

- ft\_transcendence — Backend Reference (WOZU) — for the backend pair: architecture, schema, business rules, 25 issues, port order.
- ft\_transcendence — API Contract — for both pairs: every endpoint, WebSocket events, planned contract changes.
- ft\_transcendence — Infrastructure — for infra: services, HTTPS routing, file storage, email, modules, cards.
- The reference OpenAPI file `wozu-reference-openapi.json` is shared alongside these docs.
- [ft\_transcendence — Trello Board](board.md) — for everyone: lists, sprints, card IDs, card structure, assignment, labels, counts.
- [ft\_transcendence — Backlog Snapshot](backlog.md) — every card per owner as of 2026-11-04; Trello is the live source.

**Decisions log** (byul-byul as PO keeps it current; change the status after each call)

| Date | Decision | Proposed by | Status |
| --- | --- | --- | --- |
| 2026-10-27 | Roles: byul-byul PO + infra, backend dev A Tech Lead, frontend dev A PM | Overview doc | Closed 2026-11-04: final roles below |
| 2026-10-27 | Core module set (19 points) + tier B buffer (5 points) | Overview doc | Closed 2026-11-04: final module plan below |
| 2026-10-27 | Frontend: React + TypeScript + Vite + Tailwind | Overview doc | Closed 2026-11-04: final stack below |
| 2026-10-27 | Keep the Turing Duel game | Overview doc | Closed 2026-11-04: kept, rules below |
| 2026-10-27 | New backend starts with a clean schema and fresh migrations | Backend Reference | Proposed; on the board as BE-02 |
| 2026-10-27 | One origin over HTTPS, files at `/files` | Infrastructure | Closed 2026-11-04: final stack below (INF-03, INF-04) |
| 2026-10-27 | Front proxy: nginx + ModSecurity if WAF module is claimed | Infrastructure | Closed 2026-11-04: front proxy below |
| 2026-11-04 | Roles: byul-byul Product Owner + DevOps; Khalil Tech Lead + Backend A; Nader Backend B; Zayid PM / Scrum Master + Frontend A; Ahmad Frontend B | Final card plan | Decided |
| 2026-11-04 | Modules: core 19 (M1–M12) + tier B 5 (M13–M16) + M18 Remote players (BE-33, FE-36), planned 26; tier C in Backlog: M17 AI Opponent (TC-01), M19 GDPR (TC-02, TC-03), M20 Organization system (TC-04, TC-05), started only if core + tier B are on track on Nov 22 | Final card plan | Decided |
| 2026-11-04 | Stack: React + TypeScript + Vite + Tailwind (React Router, TanStack Query, react-i18next, native WebSocket); FastAPI; PostgreSQL + PostGIS, Redis; MinIO at `/files`, Mailpit at `/mail`; Celery moderation worker (OpenAI + Whisper); Vault; Prometheus + Grafana | Final card plan | Decided |
| 2026-11-04 | Front proxy: nginx + ModSecurity CRS (INF-01) | Final card plan | Decided |
| 2026-11-04 | Languages (M10): AR, EN, AZ, TR, RU; RTL (M11) on AR | Final card plan | Decided |
| 2026-11-04 | Turing Duel rules: rooms of up to 5 with at least 1 human; hidden random bots (none, or 1–4); anonymous "Player 1…N"; one 3-minute room timer; start on the 5th join, "Start now" or timer expiry with 2+; +1 / −1 / 0 per guess. Full text in "Turing Duel rules"; input for DOC-08 | byul-byul | Decided |
| 2026-11-04 | Schedule: S1 Nov 4–10, S2 Nov 11–17, S3 Nov 18–24, S4 Nov 25–28; card due date = sprint end 18:00 Asia/Dubai (Abu Dhabi); code freeze Nov 26; first defense Sunday Nov 29; max score has priority over the date | Final card plan | Decided |
| 2026-11-04 | Trello board E3788fBx replaces 6Pob02M6; lists Backlog / To Do / In Progress / Review / Done; card ID as title prefix; branch `feat/<CARD-ID>-<short-name>` ([board.md](board.md)) | Final card plan | Decided |
| 2026-11-04 | Root README placeholder is replaced by DOC-03; its author agreed | Final card plan | Decided |
| 2026-11-05 | Front proxy: nginx + ModSecurity v3 + OWASP CRS from day one (details below) | byul-byul | Decided; Tech Lead approves through review of the INF-01 PR |
| 2026-11-08 | Compose and Makefile: `pgsty/minio`, `imresamu/postgis`, worker profile until BE-29, `fclean` keeps `.env`, host ports from `.env` (details below) | byul-byul | Decided; Tech Lead approves through review of the INF-02 PR |
| 2026-11-08 | Email at the defense: verification and password emails go only to Mailpit at `https://localhost/mail`; no Brevo or other paid email service, no `BREVO_API_KEY` in compose or the root `.env.example` (details below) | byul-byul | Decided |
| 2026-11-09 | File storage at `/files`: `minio-init` on the `pgsty/minio` image, private bucket with anonymous download on `avatars/` and `logos/` only, signing region `us-east-1` (details below) | byul-byul | Decided, except the public prefixes: proposed to Khalil (BE-08) in the INF-04 PR |
| 2026-11-12 | Every image is pinned by tag and digest; `make images-check` enforces it (INF-07) | byul-byul | Decided |
| 2026-11-12 | CI is one workflow `ci.yml` with a `ci-ok` gate; `ci-ok` is the only required check on `main` (INF-06) | byul-byul | Decided; branch protection on `main` to be applied by Khalil (repo admin) |
| 2026-11-13 | Logs and metrics kept for at most 30 days (was 15): server logs, including IP addresses in the proxy access logs, and service metrics; Privacy Policy sections 2 and 6 | byul-byul | Decided; enforced by rotation + make logs-reset, INF-07 follow-up (infrastructure doc, "Logs and retention") |
| 2026-11-15 | Monitoring (INF-08): Prometheus scrapes the API, postgres-exporter, redis-exporter and cAdvisor (from ghcr.io) every 15 s inside the Docker network; no host port, no proxy route; metrics kept 30 days, at most 1 GB (PO decision of 2026-11-12: logs and metrics at most 30 days, replacing the card's "e.g. 7 days"); `make metrics-check` runs in CI | byul-byul | Decided; review in the INF-08 PR. The Privacy Policy says at most 30 days for logs and metrics since #38 (DOC-01/02 follow-up). |
| 2026-11-15 | Dashboards (INF-09): Grafana OSS 13.3.1 at `/grafana/` behind the proxy, no host port; one user `admin` with the generated `GRAFANA_ADMIN_PASSWORD`; no anonymous access, sign-up or org creation; Secure cookie; no plugins, usage reports, update checks or news (nothing fetched from grafana.com); datasource and the dashboards "WOZU API" and "WOZU Infrastructure" provisioned read-only from files; `make env` appends missing keys to an existing `.env` without changing a value; `make grafana-check` runs in CI | byul-byul | Decided; review in the INF-09 PR (stacked on the INF-08 PR) |
| 2026-11-15 | Turing Duel voting: marks preset to human, changeable until voting ends; no 'no guess'; disconnected players keep their marks; label numbers only before results (DOC-08 follow-up) | byul-byul | Decided |
| 2026-11-16 | Turing Duel: a disconnected player still counts as a human for the winner and gets a score and an outcome; a player who comes back before voting ends can change marks; the deception rate counts preset marks and divides by all humans in the game (DOC-08 follow-up, PR #60) | byul-byul | Decided |
| 2026-11-19 | Vault (INF-12): HashiCorp Vault 2.2.2 in server mode, file storage, Shamir 3/2; `make` initializes and unseals it (`scripts/vault-init.sh`; keys file `scripts/vault-keys.local`, Git-ignored, a dev/defense trade-off); KV v2 at `secret/`, AppRole roles `api` and `worker` (token 1h/4h, secret-ids without TTL or use limit), each policy reads only its own path; file audit device on stdout; mlock on with memlock unlimited; no host port, no proxy route; `make vault-check` runs in CI | byul-byul | Decided; review in the INF-12 PR |
| 2026-11-19 | Backups (INF-14, INF-15): service `backup` (pinned `db` image plus `mc` from the pinned `minio` image, non-root); one `pg_dump -Fc` of `POSTGRES_DB` and one full `mc mirror` of the bucket a day at `BACKUP_TIME` 03:00 Asia/Dubai (a sleep loop; the card's `BACKUP_CRON` became `BACKUP_TIME`); each copy verified before it is renamed from `.partial`; the newest `BACKUP_KEEP` = 7 copies of each kept; Redis, Prometheus, Grafana and Mailpit not backed up; `make restore BACKUP=<timestamp|latest>` restores before the api starts; backups on the same host only, an off-machine copy is the production step; `make backup-check` runs in CI | byul-byul | Decided; review in the INF-14 + INF-15 PR; runbook and test log in docs/disaster-recovery.md |
| 2026-11-19 | Backup follow-up (INF-14, DOC-01): after each run, copies older than `BACKUP_MAX_AGE_DAYS` = 7 days are deleted (by the UTC timestamp in the name), then at most `BACKUP_KEEP` = 7 of each kind kept; on start, one backup at once when the newest database copy is 24 h old or more, or missing; the `backup` service starts once the api is healthy; Privacy Policy section 6 now says backups are kept for at most 7 days and then deleted | byul-byul | Decided; PR #83 follow-up; docs/disaster-recovery.md |

"Final card plan" = the plan used to set up the Trello board on 2026-11-04; its card list is in [backlog.md](backlog.md).

**Front proxy, 2026-11-05**

- **Decision:** nginx + ModSecurity v3 + OWASP Core Rule Set, using the `owasp/modsecurity-crs` nginx-alpine image at a pinned tag, as the only front door from day one. A script-generated self-signed certificate for `localhost` replaces Caddy's `tls internal`. The rule engine stays in `DetectionOnly` until card INF-11 switches it to blocking.
- **Reason:** module M13 needs ModSecurity as the only front door, and switching proxies late costs more than choosing now. Running the WAF from the first route also shows false positives while the app is being built, not on the eve of the defense.
- **Alternatives considered:** Caddy, the reference's proxy, has the simplest configuration and automatic TLS, but no ModSecurity image from the CRS project; a WAF would mean a custom build with a third-party module. Traefik has convenient Docker label routing, but a WAF is only available through a plugin, and it adds a second routing model to explain at the defense.
- **Owner:** byul-byul. **Approval:** Tech Lead, through review of the INF-01 PR.

**Compose, Makefile and secrets, 2026-11-08 (INF-02)**

- **MinIO image:** `pgsty/minio`, pinned by release tag and digest. The official `minio/minio` and `minio/mc` images were removed from Docker Hub on 2025-10-23; `pgsty/minio` rebuilds the upstream releases for amd64 and arm64. `minio-init` (bucket and policy) moves to INF-04, which also picks its client image.
- **Database image:** `imresamu/postgis:15-3.4`, pinned by tag and digest, for native arm64 on the team's Macs. Every `postgis/postgis` tag is amd64 only, so Apple Silicon would run the database emulated; `imresamu/postgis` is built from the docker-postgis sources by one of its maintainers for amd64 and arm64, with the same PostgreSQL 15 and PostGIS 3.4.
- **Worker:** defined in compose behind the `worker` profile until BE-29 adds the Celery app, so a fresh `make` does not start a container that crashes. BE-29 removes the profile line.
- **`make fclean` keeps `.env`:** it holds the hand-added `OPENAI_API_KEY`; deleting it would also make the next run generate new passwords. `fclean` removes containers, volumes, the images built here and the certificate.
- **Host ports:** 443 and 80 by default, changed with `HTTPS_PORT` / `HTTP_PORT` in `.env`; the HTTP → HTTPS redirect carries a non-default HTTPS port.
- **Variable names follow the backend code:** the JWT key is `JWT_SECRET` (BE-03), not `SECRET_KEY`; compose builds `DATABASE_URL` from `POSTGRES_*`, so the password is written once.
- **Owner:** byul-byul. **Approval:** Tech Lead, through review of the INF-02 PR.

**Email at the defense, 2026-11-08 (DOC-01)**

- **Decision:** during the defense, verification and password emails go only to Mailpit, whose inbox is at `https://localhost/mail`. No Brevo or other paid email service; no `BREVO_API_KEY` in compose or the root `.env.example`. Setup: "Email without a paid service" in [infrastructure.md](../infra/infrastructure.md#email-without-a-paid-service) (INF-05).
- **Reason:** an evaluator can sign up without a paid service, and no extra third-party processor receives user data. This matches the Privacy Policy, whose section 5 names only OpenAI and the 42 intra sign-in.
- **Owner:** byul-byul (PO).

**File storage at `/files`, 2026-11-09 (INF-04)**

- **Bucket init:** a one-shot `minio-init` service on the pinned `pgsty/minio` server image, which ships `mc` of the same release; no second image to pin. Idempotent, waits up to 60 s for MinIO; `api` starts after it completes, which also keeps `docker compose up --wait` green.
- **Access:** bucket `files` (the proxy route), private. Uploads and video reads only through presigned URLs. Anonymous download, without listing, on `avatars/` and `logos/`: proposed to Khalil for BE-08 (`avatar_url`, `logo_url`) in the INF-04 PR.
- **Same origin:** files and frontend are both `https://localhost`, so no CORS rules.
- **Signing:** the API signs for `MINIO_EXTERNAL_ENDPOINT` with `MINIO_REGION=us-east-1`, so the SDK makes no region lookup against an address that inside a container is the container itself; all server-side reads and writes use `minio:9000`.
- **Owner:** byul-byul. **Approval:** Tech Lead, through review of the INF-04 PR.
