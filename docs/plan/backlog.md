# ft\_transcendence — Backlog Snapshot

Nov 4, 2026 · @byul-byul

**Snapshot dated 2026-11-04.** Trello is the live source: https://trello.com/b/E3788fBx/fttranscendence. This file is not updated when cards change; check the board for current status, owners and due dates. How the board works (lists, sprints, labels): [board.md](board.md).

97 cards, grouped by owner. Sprint: S1 Nov 4–10 (list To Do), S2 Nov 11–17, S3 Nov 18–24, S4 Nov 25–28; "Backlog (sprint per due date)" = in Backlog, sprint set by the card's due date; "Tier C" = in Backlog, no due date, starts only if core + tier B are on track on Nov 22. "all", "all BE", "all FE" in "Depends on" mean the card depends on every card in that scope.

## byul-byul — Product Owner + DevOps (24 cards)

| ID | Title | Labels | Depends on | Sprint |
| --- | --- | --- | --- | --- |
| INF-01 | Decide front proxy: Caddy or nginx + ModSecurity CRS (decided: nginx + ModSecurity CRS) | DevOps, Security, M13, P1 | — | S1 |
| INF-02 | Set up repo layout, root compose, Makefile and init-env script | DevOps, Mandatory, P1 | INF-01 | S1 |
| INF-03 | Serve frontend, /api and /ws on one HTTPS origin | DevOps, Mandatory, P1 | INF-02 | S1 |
| INF-04 | Expose MinIO at /files with bucket init and external endpoint | DevOps, Mandatory, P1 | INF-03 | S1 |
| INF-05 | Add Mailpit at /mail for verification emails | DevOps, Mandatory, P1 | INF-03 | S1 |
| INF-06 | Add CI for backend, frontend and stack with branch protection | DevOps, P1 | INF-02, BE-01, FE-01 | S1 |
| INF-07 | Pin images, slim API image, health checks for every service | DevOps, Mandatory, M14, P2 | INF-02, BE-01 | S2 |
| INF-08 | Add Prometheus with Postgres, Redis and container exporters | DevOps, M12, P1 | INF-03, BE-30 | S2 |
| INF-09 | Provision Grafana at /grafana with dashboards | DevOps, M12, P1 | INF-08 | S2 |
| INF-10 | Add alert rules and a live alert demo | DevOps, M12, P2 | INF-09 | S3 |
| INF-11 | Tune ModSecurity CRS in blocking mode | DevOps, Security, M13, P2 | INF-01, FE-32 | S3 |
| INF-12 | Run Vault in server mode with unseal script and AppRole | DevOps, Security, M13, P2 | INF-02 | S2 |
| INF-13 | Move all service secrets from .env to Vault | DevOps, Security, M13, P2 | INF-12 | S3 |
| INF-14 | Add daily Postgres and bucket backups with 7-day retention | DevOps, Database, M14, P2 | INF-07 | S3 |
| INF-15 | Write and test the restore runbook | DevOps, Database, M14, P2 | INF-14 | S3 |
| INF-16 | Build the public status page | DevOps, M14, P2 | BE-31, INF-07 | S3 |
| FE-34 | Add the game rules page: how to play, scoring, win and loss | Frontend, M7, P2 | DOC-08 | S3 |
| DOC-01 | Write the Privacy Policy content | Docs, Mandatory, P1 | — | S2 |
| DOC-02 | Write the Terms of Service content | Docs, Mandatory, P1 | — | S2 |
| DOC-03 | Create the README skeleton with every required section (replaces the placeholder README, agreed with its author) | Docs, Mandatory, P1 | — | S1 |
| DOC-05 | Write the README Instructions and Technical Stack sections | Docs, Mandatory, P1 | DOC-03, INF-02 | S4 |
| DOC-06 | Write the README Features and Modules sections with owners and points | Docs, Mandatory, P1 | all | S4 |
| DOC-08 | Write the Turing Duel rules and approve the win condition | Docs, M7, P1 | — | S1 |
| QA-01 | Run a clean-machine defense rehearsal | DevOps, Mandatory, P1 | all | S4 |

## Khalil — Tech Lead + Backend A (16 cards)

| ID | Title | Labels | Depends on | Sprint |
| --- | --- | --- | --- | --- |
| BE-01 | Create backend skeleton: app factory, core, /api prefix, OpenAPI | Backend, M1, M5, P1 | — | S1 |
| BE-02 | Create the initial migration with the clean 17-table schema | Backend, Database, M5, P1 | BE-01 | S1 |
| BE-03 | Port register, email verification, login, refresh and logout | Backend, Mandatory, P1 | BE-02 | S1 |
| BE-04 | Port password change, forgot and reset with SMTP and frontend links | Backend, Mandatory, P1 | BE-03, INF-05 | S2 |
| BE-05 | Port /users/me with partial PATCH and trimmed UserOut | Backend, M4, P1 | BE-03 | S1 |
| BE-06 | Build the WebSocket layer: ticket auth, Redis pub/sub, presence | Backend, M2, P1 | BE-03 | S2 |
| BE-07 | Port intro video upload, confirm, post/unpost/delete and feed | Backend, M9, P1 | BE-05, INF-04 | S2 |
| BE-08 | Port avatar and logo upload with checks; return avatar_url and logo_url | Backend, Security, M4, P1 | BE-07 | S2 |
| BE-09 | Port game WebSocket with shared auth, room history and resync | Backend, M7, M8, M18, P1 | BE-06, BE-27 | S3 |
| BE-10 | Add room-scoped votes, phase_ends_at and results with winners | Backend, M7, P1 | BE-27, DOC-08 | S3 |
| BE-11 | Add OAuth 2.0 login with 42 intra | Backend, M15, P2 | BE-03 | S3 |
| BE-12 | Add rate limits to all write endpoints | Backend, Security, P2 | BE-03 | S3 |
| BE-13 | Run the backend security review: auth on every route, cross-user tests, secret scan | Backend, Security, Mandatory, P1 | all BE | S4 |
| BE-14 | Generate the database schema diagram for the README | Backend, Docs, Database, Mandatory, P2 | BE-02 | S3 |
| TC-01 | Replace template bots with an LLM-driven human-like bot | Backend, M17, P2 | BE-27 | Tier C |
| TC-02 | Add GDPR data export and deletion with email confirmation (API) | Backend, Security, M19, P2 | BE-04 | Tier C |

## Nader — Backend B (18 cards)

| ID | Title | Labels | Depends on | Sprint |
| --- | --- | --- | --- | --- |
| BE-20 | Set up backend test infrastructure: transactional fixtures, test DB | Backend, P1 | BE-01 | S1 |
| BE-21 | Port companies with GET /companies/me returning 200 null | Backend, Mandatory, P2 | BE-05 | S1 |
| BE-22 | Port friends and public profile with a single-query friends list | Backend, M3, M4, P1 | BE-05, BE-06 | S2 |
| BE-23 | Port direct conversations, participants and unread counts | Backend, M3, P1 | BE-05 | S1 |
| BE-24 | Port messages: idempotent send, edit, delete, read state, live broadcast | Backend, M3, M2, P1 | BE-23, BE-06 | S2 |
| BE-25 | Port jobs CRUD with draft/open statuses and owner counters | Backend, M6, P1 | BE-21 | S2 |
| BE-26 | Port job search: geo radius, full-text, filters, sort, cursor | Backend, M6, P1 | BE-25 | S3 |
| BE-27 | Port game matchmaking and rooms: Redis lock, random hidden bot fill, start now, phases | Backend, M7, M8, P1 | BE-06 | S2 |
| BE-28 | Port applications: apply guard, state machine, events, job views | Backend, P1 | BE-25, BE-07 | S3 |
| BE-29 | Port the moderation worker: internal download, moderation_error, beat, WS event | Backend, M9, P1 | BE-07 | S3 |
| BE-30 | Add the Prometheus /metrics endpoint | Backend, M12, P2 | BE-01 | S2 |
| BE-31 | Add /api/health with per-component status | Backend, M14, P2 | BE-01 | S2 |
| BE-32 | Add a seed script with demo accounts, jobs and videos | Backend, Database, P2 | BE-28 | S4 |
| BE-33 | Handle game disconnects: seat grace period and peer connection status | Backend, M18, P2 | BE-09 | Backlog (sprint per due date) |
| FE-14 | Build the company profile form with logo upload | Frontend, P2 | BE-21, BE-08 | S3 |
| FE-31 | Build the game lobby: participant count, start now, room countdown | Frontend, M7, M8, P1 | FE-22, BE-27 | S3 |
| QA-02 | Test multi-user concurrency in chat, game and applications | Backend, Mandatory, P1 | all | S4 |
| TC-04 | Add organization membership and roles to companies (API) | Backend, M20, P2 | BE-21 | Tier C |

## Zayid — PM / Scrum Master + Frontend A (22 cards)

| ID | Title | Labels | Depends on | Sprint |
| --- | --- | --- | --- | --- |
| PM-00 | How we work: card flow, Git rules, Definition of Done | Docs | — | S1 |
| PM-01 | Set up the sprint routine: GitHub Power-Up, weekly sync, daily update | Docs, P1 | — | S1 |
| FE-01 | Scaffold the frontend: React, TypeScript, Vite, Tailwind, lint, API types | Frontend, M1, P1 | — | S1 |
| FE-02 | Build the app shell: routing, layout, footer legal links, auth guard, 404 | Frontend, Mandatory, P1 | FE-01 | S1 |
| FE-03 | Add form validation helpers mirroring backend rules | Frontend, Mandatory, P1 | FE-01 | S1 |
| FE-04 | Build sign-up, verify-email, login and logout screens | Frontend, Mandatory, P1 | FE-02, FE-03, FE-20 | S1 |
| FE-05 | Build forgot/reset password pages and settings (change password, delete account) | Frontend, Mandatory, P2 | FE-04, BE-04 | S2 |
| FE-06 | Set up i18n with five languages (AR, EN, AZ, TR, RU) and a language switcher | Frontend, M10, P1 | FE-02 | S2 |
| FE-07 | Translate every screen into all languages | Frontend, M10, P2 | FE-06 | S3 |
| FE-08 | Add RTL support with full layout mirroring for Arabic | Frontend, M11, P2 | FE-06 | S3 |
| FE-09 | Build own profile page with edit form and avatar upload | Frontend, M4, P1 | FE-04, BE-05, BE-08 | S2 |
| FE-10 | Build the public profile page with online status and friend actions | Frontend, M3, M4, P1 | FE-09, BE-22 | S2 |
| FE-11 | Build the friends page: list, incoming requests, remove | Frontend, M3, M4, P1 | BE-22 | S2 |
| FE-13 | Render Privacy Policy and Terms of Service pages | Frontend, Mandatory, P1 | DOC-01, DOC-02 | S2 |
| FE-16 | Test and fix in Firefox and Safari or Edge, document limits | Frontend, M16, P2 | all FE | S4 |
| FE-17 | Make every flow console-clean in Chrome | Frontend, Mandatory, P1 | all FE | S4 |
| FE-27 | Build employer job pages: create, edit, delete, my jobs with counters | Frontend, P1 | BE-25 | S3 |
| DOC-04 | Write the README Project Management section | Docs, Mandatory, P2 | DOC-03 | S2 |
| DOC-07 | Collect individual contributions and AI usage for the README | Docs, Mandatory, P1 | all | S4 |
| QA-03 | Write the module demo script | Docs, P1 | all | S4 |
| QA-04 | Hold per-module walkthroughs and a live-change rehearsal | Docs, P1 | QA-03 | S4 |
| TC-03 | Build the GDPR privacy center page | Frontend, M19, P2 | TC-02 | Tier C |

## Ahmad — Frontend B (17 cards)

| ID | Title | Labels | Depends on | Sprint |
| --- | --- | --- | --- | --- |
| FE-12 | Show live online status from presence events | Frontend, M2, M4, P2 | FE-22, FE-11 | S3 |
| FE-15 | Build "My applications" with statuses and withdraw | Frontend, P2 | BE-28 | S3 |
| FE-20 | Build the API client with token refresh and error handling | Frontend, M1, P1 | FE-01 | S1 |
| FE-21 | Build reusable UI components on design tokens | Frontend, Mandatory, P1 | FE-01 | S1 |
| FE-22 | Build the WebSocket client: ticket auth, reconnect, event routing | Frontend, M2, P1 | FE-20, BE-06 | S2 |
| FE-23 | Build the jobs search page with filters, sorting and load more | Frontend, M6, P1 | FE-21 | S2 |
| FE-24 | Build the job detail page with apply flow and guard redirects | Frontend, P1 | FE-23, BE-28 | S2 |
| FE-25 | Build video resume recording and upload with progress | Frontend, M9, P1 | FE-21, BE-07, INF-04 | S2 |
| FE-26 | Build "My videos" with moderation status, post, unpost, delete | Frontend, M9, P2 | FE-25, BE-29 | S3 |
| FE-28 | Build the employer applications view with videos and status changes | Frontend, P1 | FE-27, BE-28 | S3 |
| FE-29 | Build the conversation list with unread counts | Frontend, M3, P1 | FE-22, BE-23 | S2 |
| FE-30 | Build the chat thread: history, send, edit, delete, read receipts, live | Frontend, M3, M2, P1 | FE-29, BE-24 | S3 |
| FE-32 | Build the game room: discussion with countdown, voting, results | Frontend, M7, M8, P1 | FE-31, BE-09, BE-10 | S3 |
| FE-33 | Restore the game room after reload or reconnect | Frontend, M7, M8, M18, P2 | FE-32, BE-09 | S3 |
| FE-35 | Run the accessibility and responsive pass on all screens | Frontend, Mandatory, P2 | all FE | S4 |
| FE-36 | Show connection state and reconnect progress in the game room | Frontend, M18, P2 | FE-33, BE-33 | Backlog (sprint per due date) |
| TC-05 | Build the organization management UI | Frontend, M20, P2 | TC-04 | Tier C |
