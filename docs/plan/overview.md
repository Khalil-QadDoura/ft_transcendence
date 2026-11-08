# ft\_transcendence — Overview & Plan

Original plan: Oct 27, 2026 · @byul-byul

PM-01 reconciliation: Nov 8, 2026 · @zayidelkhair, with Codex assistance. Decisions below follow the active [PM-00](https://trello.com/c/twqpeAfN) and [PM-01](https://trello.com/c/F551icOK) cards. Historical reference-backend test counts are not claims about the current team backend.

## TL;DR

We build **WOZU Web**: a job platform where candidates apply with a short video instead of a CV, talk to employers in real-time chat, and play a social-deduction mini-game ("Turing Duel"). The WOZU backend is our reference; we write a new backend and a web frontend on top of it.

- **Target:** 14 mandatory points + 5 bonus = 19, the maximum that counts. We plan 26 points (including M18 Remote players) so that one or two modules can fail at the defense without losing the maximum.
- **Good news:** the reference backend already covers most of the 19 core points. I ran it: all 36 migrations apply on a clean database and all 127 tests pass.
- **Real work:** a web frontend from scratch, HTTPS for everything (including file uploads), Privacy Policy and Terms of Service pages, and fixing about 20 issues we must not copy.

**Decided in the active board plan:**

1. Burhan is PO + DevOps; Khalil is Tech Lead + Backend A; Nader is Backend B; Zayid is PM / Scrum Master + Frontend A; Ahmad is Frontend B.
2. The original 19-point core + 5-point buffer remains, with M18 Remote players (+2) added to planned scope: 26 planned points, still capped at 19 counted points. Planning a module does not mean it has been implemented or accepted.
3. React + TypeScript + Vite + Tailwind; retain Turing Duel.
4. Five frontend languages: English, Arabic, Azerbaijani, Turkish and Russian; Arabic includes RTL layout.
5. First defense target: November 29, 2026. S1 Nov 4–10; S2 Nov 11–17; S3 Nov 18–24; S4 Nov 25–28, with code freeze Nov 26. Sprint deadlines are 18:00 Baku. Quality takes priority over the defense date (PM-00).

The weekly meeting slot, team-chat location and daily update deadline are **not yet agreed**. See [sprint routine](sprint-routine.md); no calendar invitation or pinned chat message is claimed.

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
| Every browser connection over HTTPS | API yes (Caddy); file uploads go to MinIO over plain HTTP on an internal host | Serve frontend, API, WebSocket and MinIO through Caddy TLS | Infra |
| Chrome, no console errors or warnings | n/a | Avoid expected 4xx responses in normal flows (Chrome logs them as errors), clean React warnings | FE + BE |
| Responsive, accessible frontend with a CSS framework | n/a | Tailwind (or similar), mobile-first layouts | FE |
| Forms validated on frontend and backend | Backend validates with Pydantic; avatar extension and object key not validated | Mirror rules in frontend forms; close backend gaps | FE + BE |
| Sign up and log in securely, hashed + salted passwords | Yes (Argon2id) | Keep; make email verification work without a paid email service | BE + Infra |
| Database with a clear schema and relations | Works, but 36 migrations carry legacy tables, two chat systems, unused columns | Start the new backend with a clean schema and a fresh migration history | BE |
| Multiple users at once, no race conditions | Mostly; game matchmaking would race with more than one API worker | One worker or a Redis lock on the matchmaking tick | BE |
| One-command deployment with containers | `docker compose up -d` (backend only) | Root compose file including the frontend; `make` wrapper | Infra |
| `.env` ignored by Git + `.env.example` | Yes | Keep, extend for new services | Infra |
| Git: commits from all members, clear messages | n/a for the new repo | Conventions below; never import the reference as one big commit | All |
| README with all required sections | One-line README | PO owns it; every member writes their part | All |
| Team roles documented | Active PM-00 names the five owners | Keep README, overview and board ownership aligned | PO + PM |

## Roles

Roles recorded in the active PM-00 card:

| Person | Track | Role(s) | Main responsibilities |
| --- | --- | --- | --- |
| Burhan (@byul-byul) | Infrastructure | Product Owner + Developer (DevOps) | Product vision, backlog priorities, accepts finished cards, README and legal content; containers, HTTPS, monitoring and security |
| Khalil (@Khalil-QadDoura) | Backend A | Tech Lead / Architect + Developer | Backend architecture, API contract, auth/users/presence, intro-video upload (BE-07), critical reviews and code quality |
| Nader (@NaderZico) | Backend B | Developer | Jobs, applications, moderation worker, friends/chat REST and game backend |
| Zayid (@zayidelkhair; Trello @noobthinker) | Frontend A | PM / Scrum Master + Developer | Board, deadlines, dependencies and sprint routine; shell, auth, validation, i18n/RTL, profiles/friends and legal rendering |
| Ahmad (@a7mdwr) | Frontend B | Developer | Shared API client (FE-20), shared UI/theme (FE-21), jobs/applications/video/chat/game screens |

Each member must be able to explain the whole project and make a small code change during the defense. Track summaries are not reassignment: the live card's Owner line is authoritative, including cross-track cards.

## Module plan

Core set = 19 points, built mostly on what the reference already does; buffer tier B adds 5 more for 24, and the decided M18 Remote players adds 2 for a planned 26. A module counts only if it fully works at the defense, so the buffer is insurance, not extra credit.

**Core (19 points)**

| # | Module | Type | Pts | Reference today | Main work for us | Track |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Frameworks for frontend and backend | Major | 2 | FastAPI | React frontend | FE + BE |
| 2 | Real-time features (WebSockets) | Major | 2 | `/ws` with Redis pub/sub | Client reconnect, broadcast edits / deletes, presence in Redis | BE + FE |
| 3 | User interaction: chat, profile, friends | Major | 2 | All three exist | Chat, profile and friends UI | FE |
| 4 | Standard user management | Major | 2 | Profile edit, avatar upload, friends + online status | Avatar display URL, default avatar, profile page | BE + FE |
| 5 | ORM | Minor | 1 | SQLAlchemy 2 async + Alembic | Keep | BE |
| 6 | Advanced search: filters, sorting, pagination | Minor | 1 | Job search with geo, salary, schedule, keyword, sort, cursor | Search UI with filters and paging | FE |
| 7 | Web-based game | Major | 2 | Turing Duel backend | Game UI, clear win / loss result, room history endpoint | BE + FE |
| 8 | Multiplayer game, 3+ players | Major | 2 | Rooms of 2 to 5 | Minimum room size 3, state sync for all clients | BE + FE |
| 9 | Content moderation AI | Minor | 1 | Video moderation with Whisper + OpenAI moderation | Fix the `moderation_error` enum bug; demo both approve and reject | BE |
| 10 | Multiple languages (3+) | Minor | 1 | Reference language set differs | EN / AR / AZ / TR / RU, language switcher | FE |
| 11 | Right-to-left language support | Minor | 1 | Arabic already in the language set | Full layout mirroring | FE |
| 12 | Monitoring with Prometheus + Grafana | Major | 2 | Structured JSON logs, health endpoint | Metrics, exporters, dashboards, alerts, secured Grafana | Infra |

**Buffer tier B (+5; original subtotal 24)**

| # | Module | Type | Pts | Why it is cheap | Track |
| --- | --- | --- | --- | --- | --- |
| 13 | WAF / ModSecurity + HashiCorp Vault | Major | 2 | Pure infrastructure, no app redesign | Infra |
| 14 | Health check, status page, automated backups, recovery | Minor | 1 | Health endpoint exists; add `pg_dump` schedule and a restore runbook | Infra |
| 15 | OAuth 2.0 (42 intra) | Minor | 1 | One login flow on top of the existing token issuing | BE + FE |
| 16 | Additional browsers (Firefox, Safari or Edge) | Minor | 1 | Test and fix, document limits | FE |

**Additional decided scope: M18 Remote players (+2, planned total 26).** Two players on separate computers must play the same game; reconnect and room resync are implementation work, not already completed. M18 is no longer optional Tier C.

**Tier C (only if ahead of schedule):** AI Opponent (Major, 2) needs the bot rewritten, today it sends random template lines and a careful evaluator may reject it; GDPR features (Minor, 1) fit the Privacy Policy; Organization system (Major, 2) would bring back WOZU company teams.

**Point math:** core 19 = 7 Majors (14) + 5 Minors (5). Tier B: 1 Major + 3 Minors = 5. M18 adds another Major (2): total planned = 19 + 5 + 2 = 26; at most 19 count. If two core minors fail, tier B still keeps us at 19+. Each claim needs its own working demonstration.

## Work split

Each person owns whole modules end to end inside their track, so the README can name one owner per module and the Git history backs it up. Pairs split by domain, not by layer.

| Person | Owns (modules / areas) | Shared |
| --- | --- | --- |
| Khalil (Backend A / Tech Lead) | Auth + users + avatar (4), intro-video upload (BE-07), WebSocket layer + presence (2), OAuth 42 (15), project skeleton, schema and migrations, API contract | ORM (5), game backend with B |
| Nader (Backend B) | Jobs + search (6), applications, moderation worker (9), friends and chat REST (3), game backend: rooms, phases, results (7, 8) | Fixes from the issue list |
| Zayid (Frontend A / PM) | App shell, routing, auth screens, shared validation, i18n + RTL (10, 11), profile + friends UI, legal pages | Browser testing (16) |
| Ahmad (Frontend B) | Shared API client (FE-20), UI/theme primitives (FE-21), jobs search + job detail + apply flow, video recording and upload UI, chat UI, game UI (7, 8) | WebSocket client with A |
| Burhan (PO + Infra) | Compose + Caddy + TLS for every route, MinIO over HTTPS, local mail catcher, Prometheus + Grafana (12), WAF + Vault (13), backups + status page (14), CI checks | README, Privacy Policy and ToS content, backlog |

The frontend is the critical path: both frontend devs start on day one against the API contract and the reference backend running locally (it works today), not waiting for the new backend.

## Defense risks

The biggest risks are environment ones, not code: email, OpenAI and HTTPS uploads each depend on setup that must work on the evaluator's machine.

| Risk | Effect at defense | Fix | Owner |
| --- | --- | --- | --- |
| Email verification needs a Brevo API key; without it the link only goes to the server log | Evaluator cannot finish sign-up | Mailpit container (local mail catcher with a web inbox) + SMTP sender; links point to frontend pages | Infra + BE |
| Uploads go to `minio:9000` over HTTP | Avatar and video upload fail in the browser; HTTPS rule broken | MinIO behind Caddy TLS + bucket CORS; backend checks the object exists on confirm | Infra + BE |
| Moderation needs a funded OpenAI key; on API errors it approves everything | Moderation module looks like it does nothing | Real key in `.env` on defense day; demo one approved and one rejected video | BE |
| Chrome logs every 4xx response as a console error | "No console errors" fails, e.g. `GET /companies/me` returns 404 for job seekers | Normal flows return 200 with empty data; refresh tokens before expiry | BE + FE |
| Self-signed certificate on localhost | One browser warning; WebSocket fails if served from another origin | Serve frontend, `/api` and `/ws` from one origin through Caddy | Infra |
| Matchmaking loop runs in every API worker | Duplicate rooms under load | Keep one worker or take a Redis lock per tick | BE |
| Template bot | AI Opponent claim rejected | Do not claim AI Opponent unless the bot is rewritten (tier C) | BE |
| Big import commits, one person's code | Git history shows poor work distribution | Port the reference module by module, one card and one PR each, owner commits | All |
| A member cannot explain another part | Live code-change request fails | Code reviews across pairs; a 30-minute walkthrough per module before the defense | PM |

## Ways of working

Every change travels card → branch → PR → review → merge → card moved, so the [Trello board](https://trello.com/b/E3788fBx/fttranscendence) and the Git history tell the same story at the defense.

**Trello board**

- Lists: Backlog → To Do → In Progress → Review → Done. One-week sprints; the PO orders Backlog, the PM runs To Do. The owner joins their card before starting. Done requires a merged PR and all acceptance gates (PM-00).
- Labels: track (`Frontend`, `Backend`, `DevOps`, `Docs`), subject module (`M1`–`M20`), required scope (`Mandatory`), priority (`P1`, `P2`).
- One owner per card; a reviewer from the other pair is added when the card reaches Review.
- Turn on the GitHub Power-Up so PRs and commits appear on the card.

**Card format**

```markdown
Title: <verb> <what> — e.g. "Add avatar display URL to profile endpoints"

Why: one line linking to the module or mandatory item
Done when:
- [ ] acceptance criterion 1
- [ ] acceptance criterion 2
- [ ] tests added / updated
- [ ] API contract doc updated (if the API changed)
Depends on: #<card number>
```

**Git**

- `main` is protected: merge only through a PR with one approving review and green CI.
- Branch name: `<type>/<card-id>-<short-name>`, e.g. `feat/FE-04-auth-screens`, `fix/BE-10-vote-room-check`.
- Commit message: `<type>(<scope>): <summary> (<card-id>)`, types `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`. Example: `fix(game): reject votes for other rooms (BE-10)`.
- Small PRs (under \~400 changed lines), one card each. Squash merge keeps one clear commit per card on `main`.
- Everyone commits their own work from their own account; pair work uses `Co-authored-by:` lines.
- Weekly sync (30 min, PM leads) + async daily update in the team chat: done, next, blocked.

## Related documents and decisions

- ft\_transcendence — Backend Reference (WOZU) — for the backend pair: architecture, schema, business rules, 25 issues, port order.
- ft\_transcendence — API Contract — for both pairs: every endpoint, WebSocket events, planned contract changes.
- ft\_transcendence — Infrastructure — for infra: services, HTTPS routing, file storage, email, modules, cards.
- The reference OpenAPI file `wozu-reference-openapi.json` is shared alongside these docs.

**Decisions log** (PO keeps it current; PM-01 explicitly requests the recorded decisions below. Operational agreements still pending are listed separately in the sprint routine.)

| Decision | Proposed by | Status |
| --- | --- | --- |
| Named roles above: Burhan PO, Khalil Tech Lead, Zayid PM; Nader Backend B, Ahmad Frontend B | PM-00 | Decided |
| Core (19) + tier B (5) + M18 Remote players (2); 26 planned, max 19 counted | PM-01 | Decided |
| Frontend: React + TypeScript + Vite + Tailwind | PM-01; FE-01 merged | Decided |
| Keep the Turing Duel game | PM-01 | Decided |
| Five languages: EN / AR / AZ / TR / RU; Arabic RTL | PM-01 / frontend plan | Decided |
| First defense Nov 29, 2026; code freeze Nov 26; quality may move defense | PM-00 / PM-01 | Decided |
| New backend starts with a clean schema and fresh migrations | BE-02, merged PR #7 | Decided / implemented schema |
| One origin over HTTPS, files at `/files` | Infrastructure | Proposed |
| Front proxy: nginx + ModSecurity if WAF module is claimed | Infrastructure | Proposed |
