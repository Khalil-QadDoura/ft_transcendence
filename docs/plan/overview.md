# ft\_transcendence — Overview & Plan

Oct 27, 2026 · @boss

## TL;DR

We build **WOZU Web**: a job platform where candidates apply with a short video instead of a CV, talk to employers in real-time chat, and play a social-deduction mini-game ("Turing Duel"). The WOZU backend is our reference; we write a new backend and a web frontend on top of it.

- **Target:** 14 mandatory points + 5 bonus = 19, the maximum that counts. We plan 24 points so that one or two modules can fail at the defense without losing the maximum.
- **Good news:** the reference backend already covers most of the 19 core points. I ran it: all 36 migrations apply on a clean database and all 127 tests pass.
- **Real work:** a web frontend from scratch, HTTPS for everything (including file uploads), Privacy Policy and Terms of Service pages, and fixing about 20 issues we must not copy.

**Decide on the next call:**

1. Roles: who is PO, PM / Scrum Master, Tech Lead (proposal below).
2. Module set: confirm the 19-point core and the order of buffer modules.
3. Frontend framework (proposal: React + TypeScript + Vite + Tailwind).
4. Do we keep the Turing Duel game? Four core points depend on it.
5. The defense date, so the PM can set milestones.

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
| Team roles documented | Not yet | Decide on the next call | PO |

## Roles

Proposal: spread the three lead roles across the three tracks, so each sub-team has a lead and every member has a visible responsibility to explain at the defense. The subject allows combined roles in any team size.

| Person | Track | Role(s) | Main responsibilities |
| --- | --- | --- | --- |
| You | Infrastructure | Product Owner + Developer (DevOps) | Product vision (you know WOZU best), backlog priorities, accepts finished cards, README and legal pages content; Docker, Caddy/TLS, monitoring, security modules |
| Backend dev A | Backend | Tech Lead / Architect + Developer | Backend architecture and API contract, stack decisions, reviews critical PRs, code quality rules |
| Backend dev B | Backend | Developer | Ports and owns backend modules (see Work split) |
| Frontend dev A | Frontend | PM / Scrum Master + Developer | Runs the Trello board, weekly sync, tracks deadlines and blockers, keeps the risk list |
| Frontend dev B | Frontend | Developer | Owns frontend modules (see Work split) |

**Alternative:** you as Tech Lead + DevOps, a frontend dev as PO. Choose it if the team wants one person to hold the full technical picture. Its cost: three hats on one person and less leadership visible from the backend pair.

Whatever the split, each member must be able to explain the whole project and make a small code change during the defense.

## Module plan

Core set = 19 points, built mostly on what the reference already does; buffer tier B adds 5 more for a planned 24. A module counts only if it fully works at the defense, so the buffer is insurance, not extra credit.

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
| 10 | Multiple languages (3+) | Minor | 1 | WOZU app had EN / AR / ID / TR | i18n in the web app, language switcher | FE |
| 11 | Right-to-left language support | Minor | 1 | Arabic already in the language set | Full layout mirroring | FE |
| 12 | Monitoring with Prometheus + Grafana | Major | 2 | Structured JSON logs, health endpoint | Metrics, exporters, dashboards, alerts, secured Grafana | Infra |

**Buffer tier B (+5, planned total 24)**

| # | Module | Type | Pts | Why it is cheap | Track |
| --- | --- | --- | --- | --- | --- |
| 13 | WAF / ModSecurity + HashiCorp Vault | Major | 2 | Pure infrastructure, no app redesign | Infra |
| 14 | Health check, status page, automated backups, recovery | Minor | 1 | Health endpoint exists; add `pg_dump` schedule and a restore runbook | Infra |
| 15 | OAuth 2.0 (42 intra) | Minor | 1 | One login flow on top of the existing token issuing | BE + FE |
| 16 | Additional browsers (Firefox, Safari or Edge) | Minor | 1 | Test and fix, document limits | FE |

**Tier C (only if ahead of schedule):** AI Opponent (Major, 2) needs the bot rewritten, today it sends random template lines and a careful evaluator may reject it; Remote players (Major, 2) needs reconnect and room resync; GDPR features (Minor, 1) fit the Privacy Policy; Organization system (Major, 2) would bring back WOZU company teams.

**Point math:** core 19 = 7 Majors (14) + 5 Minors (5). Tier B: 1 Major + 3 Minors = 5. If two core minors fail, tier B still keeps us at 19+.

## Work split

Each person owns whole modules end to end inside their track, so the README can name one owner per module and the Git history backs it up. Pairs split by domain, not by layer.

| Person | Owns (modules / areas) | Shared |
| --- | --- | --- |
| Backend dev A (Tech Lead) | Auth + users + avatar (4), WebSocket layer + presence (2), OAuth 42 (15), project skeleton, schema and migrations, API contract | ORM (5), game backend with B |
| Backend dev B | Jobs + search (6), applications, video upload + moderation (9), friends and chat REST (3), game backend: rooms, phases, results (7, 8) | Fixes from the issue list |
| Frontend dev A (PM) | App shell, routing, auth screens, design tokens, i18n + RTL (10, 11), profile + friends UI, legal pages | Browser testing (16) |
| Frontend dev B | Jobs search + job detail + apply flow, video recording and upload UI, chat UI, game UI (7, 8) | WebSocket client with A |
| You (PO + Infra) | Compose + Caddy + TLS for every route, MinIO over HTTPS, local mail catcher, Prometheus + Grafana (12), WAF + Vault (13), backups + status page (14), CI checks | README, Privacy Policy and ToS content, backlog |

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

Every change travels card → branch → PR → review → merge → card moved, so the [Trello board](https://trello.com/b/6Pob02M6/transcendence) and the Git history tell the same story at the defense.

**Trello board**

- Lists: Backlog → Sprint → In Progress → Review → Done. One-week sprints; the PO orders Backlog, the PM runs Sprint.
- Labels: track (`FE`, `BE`, `INFRA`, `DOCS`), module (`M1 Frameworks` … `M16 Browsers`, `Mandatory`), priority (`P1`, `P2`).
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
- Branch name: `<type>/<card-number>-<short-name>`, e.g. `feat/42-avatar-url`, `fix/57-vote-room-check`.
- Commit message: `<type>(<scope>): <summary> (#<card>)`, types `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`. Example: `feat(game): reject votes for participants of other rooms (#57)`.
- Small PRs (under \~400 changed lines), one card each. Squash merge keeps one clear commit per card on `main`.
- Everyone commits their own work from their own account; pair work uses `Co-authored-by:` lines.
- Weekly sync (30 min, PM leads) + async daily update in the team chat: done, next, blocked.

## Related documents and decisions

- ft\_transcendence — Backend Reference (WOZU) — for the backend pair: architecture, schema, business rules, 25 issues, port order.
- ft\_transcendence — API Contract — for both pairs: every endpoint, WebSocket events, planned contract changes.
- ft\_transcendence — Infrastructure — for infra: services, HTTPS routing, file storage, email, modules, cards.
- The reference OpenAPI file `wozu-reference-openapi.json` is shared alongside these docs.

**Decisions log** (the PO keeps it current; change the status after each call)

| Decision | Proposed by | Status |
| --- | --- | --- |
| Roles: you PO + infra, backend dev A Tech Lead, frontend dev A PM | Overview doc | Proposed |
| Core module set (19 points) + tier B buffer (5 points) | Overview doc | Proposed |
| Frontend: React + TypeScript + Vite + Tailwind | Overview doc | Proposed |
| Keep the Turing Duel game | Overview doc | Proposed |
| New backend starts with a clean schema and fresh migrations | Backend Reference | Proposed |
| One origin over HTTPS, files at `/files` | Infrastructure | Proposed |
| Front proxy: nginx + ModSecurity if WAF module is claimed | Infrastructure | Proposed |
