*This project has been created as part of the 42 curriculum by bhajili, kqaddour, nakhalil, zsid-ele, aradwan.*

# WOZU Web

> Status: in development (sprint 1 of 4). Sections with a TODO comment are filled by the owner card named in the comment; nothing below describes a feature as finished unless it exists in the repository.
<!-- TODO DOC-06 (byul-byul): remove the Status line before submission. -->

## Description

**WOZU Web** is a job platform for the web. A candidate applies to a job with a short video instead of a CV, talks to employers in real-time chat, and can play a social-deduction mini-game called the Turing Duel. The project is a new backend and a new web frontend, built on top of the WOZU backend as a reference.

**Goal:** a complete web application (frontend, backend, database) that meets the ft_transcendence subject and runs with a single command.

**Key features (planned; the Features List section records what is implemented):**

- Video-based job applications instead of CVs.
- Real-time chat between candidates and employers.
- Turing Duel: a multiplayer mini-game in which humans and bots chat, and each human guesses who is a bot. The full rules are in [docs/game/turing-duel-rules.md](docs/game/turing-duel-rules.md).

Planning documents (roles, module plan, API contract, infrastructure) are in [docs/](docs/README.md).

## Instructions

<!-- TODO DOC-05 (byul-byul): prerequisites (software, tools, versions), .env setup, step-by-step run with make, Mailpit at /mail. Only commands that work. -->

**Prerequisites:** Docker Engine 25 or newer (the health checks use `start_interval`) with Docker Compose v2, make, bash and openssl.

## Resources

<!-- TODO DOC-07 (Zayid): classic references (documentation, articles, tutorials) and the final description of how AI was used, for which tasks and which parts. -->

**AI usage (running list, incomplete until DOC-07):**

- The plan documents in `docs/` were drafted with AI assistance (Claude) and reviewed by the team.
- The Trello card plan and card texts were drafted with Claude and approved by the Product Owner.
- DOC-08 (the Turing Duel rules text) was written with Claude Code.
- INF-01 (nginx + ModSecurity proxy configuration, certificate script, verification) was written with Claude Code.
- Each owner must review, test and be able to explain their AI-assisted work; this list is not evidence that every owner has already completed that preparation.
- Codex assisted the November 8 review of this README skeleton, including checking required sections and correcting the owner-preparation statement. This does not replace each owner's review or defense practice.

## Team Information

| Member | 42 login | GitHub | Role(s) | Responsibilities |
| --- | --- | --- | --- | --- |
| Burhan | bhajili | byul-byul | Product Owner + Developer (DevOps) | Product vision, backlog priorities, acceptance of finished cards, README and legal pages content; Docker, nginx + ModSecurity / TLS, monitoring, security modules |
| Khalil | kqaddour | Khalil-QadDoura | Technical Lead + Developer (Backend A) | Backend architecture and API contract, stack decisions, review of critical PRs, code quality rules |
| Nader | nakhalil | NaderZico | Developer (Backend B) | Ports and owns backend modules |
| Zayid | zsid-ele | zayidelkhair | Project Manager / Scrum Master + Developer (Frontend A) | Runs the Trello board and the weekly sync, tracks deadlines and blockers, keeps the risk list; frontend modules |
| Ahmad | aradwan | a7mdwr | Developer (Frontend B) | Owns frontend modules |

<!-- TODO DOC-06 (byul-byul): each member checks their own row before submission; add the module names once the work split is final. -->

## Project Management

The team divides work by ownership: Burhan is Product Owner and owns infrastructure; Khalil is Technical Lead and Backend A; Nader is Backend B; Zayid is Project Manager / Scrum Master and Frontend A; Ahmad is Frontend B. The [backlog](docs/plan/backlog.md) maps each feature to one owner and its dependencies. The Product Owner maintains priorities and the [decisions log](docs/plan/overview.md); the Technical Lead reviews architecture and API decisions. Zayid tracks deadlines, blockers and review handoffs.

We plan in one-week sprints: November 4–10, 11–17 and 18–24, followed by a shorter November 25–28 sprint. Code freeze is November 26; the first defense is November 29. Deadlines are 18:00 Abu Dhabi (Asia/Dubai, UTC+4). The [Trello board](https://trello.com/b/E3788fBx/fttranscendence) is the live work tracker: **Backlog → To Do → In Progress → Review → Done**. A card identifies its owner, sprint, priority, dependencies and “Done when” checklist. Card IDs such as FE-06 identify work; GitHub PR numbers identify review discussions.

Each card gets a focused branch and pull request. Branches follow `feat/FE-06-i18n-setup` (or `fix/…`, `docs/…`); commits follow `<type>(<scope>): <summary> (<CARD-ID>)`. PRs link the Trello card, describe behavior and validation, and request review from the other pair. The team rule is review within 24 hours. Applicable frontend/backend CI must pass, feedback must be addressed and approval obtained before squash-merging into `main`. A dependent PR names its parent and is retargeted and checked after the parent lands. `main` already requires one approving review and disallows force pushes. Making CI a required check and applying protection to administrators remain INF-06 work.

The [PM-00 board guide](docs/plan/board.md) defines the workflow and Definition of Done. An open PR is **Review**, not **Done**: merge and the card's complete acceptance evidence are required. After a merge, the owner makes a small live change and explains/tests it as defense practice. Study notes support that preparation; they do not replace the owner's demonstration.

Communication uses the team’s WhatsApp group for daily coordination and the daily Done / Next / Blocked update, Trello card comments for implementation questions and blockers, and GitHub for code feedback and review requests. The [PM-01 sprint routine](docs/plan/sprint-routine.md) contains the 30-minute weekly agenda and the daily **Done / Next / Blocked** template. As of November 11, the proposed Tuesday 18:30 weekly slot, weekday 22:00 update cutoff and call details still need team agreement. WhatsApp is the confirmed coordination channel; calendar invitations and pinning the daily-update format are still pending. The GitHub Power-Up is enabled, but repository authorization/linking remains an open PM-01 action; an ordinary PR attachment is not proof of that connection.

This is the Sprint 2 process record, owned by Zayid (DOC-04). Refresh it in Sprint 4 against the decisions, meeting records and actual tool configuration so the final README describes what the team did.

## Technical Stack

Decided stack (starting point):

- Frontend: React, TypeScript, Vite, Tailwind CSS; React Router, TanStack Query, react-i18next, native WebSocket.
- Backend: FastAPI; Celery moderation worker.
- Data: PostgreSQL with PostGIS, Redis; MinIO for files (served at `/files`).
- Email in development: Mailpit (served at `/mail`).
- Edge and operations: nginx with ModSecurity (OWASP CRS) as front proxy; Vault; Prometheus and Grafana.

<!-- TODO DOC-05 (byul-byul): justification for each major technical choice, including why PostgreSQL. -->

## Database Schema

The data lives in PostgreSQL 15 with PostGIS: 17 tables, created by the Alembic migrations in `backend/alembic/versions/` (the SQLAlchemy models are in `backend/app/<domain>/models.py`).

![Database schema of WOZU Web: every table with its columns and types, and the foreign keys between them](docs/db/schema.svg)

**How to read the diagram.** Each box is a table: its columns in order, the type in brackets, `NOT NULL` when a value is required, the primary key underlined. Each dashed line is a foreign key, from the `id` it points at to the column that holds it; the label at each end says how many rows can be there: `1`, `{0,1}` (the column may be empty) or `0..N`. To see it larger, open [docs/db/schema.svg](docs/db/schema.svg).

**Generated, never drawn by hand.** `make schema-diagram` (the script `scripts/gen-schema-diagram.sh`, Docker only, no `.env`) starts a throwaway PostgreSQL + PostGIS from the stack's image, runs `alembic upgrade head`, and draws every table of the resulting database with [eralchemy](https://github.com/eralchemy/eralchemy) and Graphviz into `docs/db/schema.svg`, then removes what it started. After a migration that changes the schema, run it again and commit the new picture.

**In every table:** `id` BIGINT primary key, numbered by the database; `created_at` and `updated_at` TIMESTAMPTZ, filled in by the database. A status or a type with a fixed list of values is a PostgreSQL enum (for example `user_status`: `active`, `deleted`). The app does not delete users, companies, jobs or videos; it marks them `deleted` (soft delete). "On delete" says what happens to a row when the row it points at is deleted: CASCADE deletes it too, SET NULL keeps it and empties the link.

**Accounts and friends**

| Table | Purpose | Key fields and types | Relations (on delete) |
| --- | --- | --- | --- |
| `users` | One account, candidate or employer | `email` VARCHAR(255), unique; `password_hash` VARCHAR(255); `is_email_verified` BOOLEAN; profile: `first_name`, `last_name` VARCHAR(50), `position` VARCHAR(100), `birth_date` DATE, `bio` VARCHAR(500), `avatar_object_key` VARCHAR(500); `token_version` INTEGER; `status` user_status (`active`, `deleted`) | Almost every other table points here |
| `refresh_tokens` | One refresh token given out at login or refresh; the token itself is not stored | `jti` VARCHAR(64), unique (the token's id); `token_version` INTEGER; `expires_at` TIMESTAMPTZ; `revoked` BOOLEAN | `user_id` → `users` (CASCADE) |
| `password_reset_tokens` | One "forgot password" link, usable once | `token` VARCHAR(64), unique; `expires_at` TIMESTAMPTZ; `used_at` TIMESTAMPTZ | `user_id` → `users` (CASCADE) |
| `friendships` | A friend request, then the friendship | `requester_id`, `addressee_id` BIGINT; `status` friendship_status (`pending`, `accepted`, `declined`); never with oneself; one pending or accepted row per pair | `requester_id`, `addressee_id` → `users` (CASCADE) |

**Companies, jobs and applications**

| Table | Purpose | Key fields and types | Relations (on delete) |
| --- | --- | --- | --- |
| `companies` | The employer side of a user | `name` VARCHAR(150); `description` TEXT; `logo_object_key` VARCHAR(500); `country`, `city`, `district` VARCHAR(100); `country_code` VARCHAR(2); `status` company_status (`active`, `deleted`); one active company per owner | `owner_user_id` → `users` (CASCADE); `created_by_id`, `updated_by_id` → `users` (SET NULL) |
| `jobs` | A vacancy of a company | `title` VARCHAR(200); `description` TEXT; `status` job_status (`draft`, `open`, `deleted`); `latitude`, `longitude` DOUBLE PRECISION (range checked); `location` VARCHAR(150); `salary_amount` NUMERIC(12, 2), not negative; `salary_type`, `schedule`, `urgency` enums; `salary_currency` VARCHAR(3) (ISO 4217); `location_point` geography(POINT,4326), computed from the coordinates, for distance search; `search_vector` TSVECTOR, filled by a trigger, for keyword search | `owner_id` → `companies` (CASCADE); `created_by_id`, `updated_by_id` → `users` (SET NULL) |
| `job_views` | One counted view of a job page | `viewed_at` TIMESTAMPTZ | `job_id` → `jobs` (CASCADE); `viewer_id` → `users` (SET NULL; empty for a visitor who is not logged in) |
| `applications` | A candidate applying to a job, once per job | `status` application_status (`submitted`, `viewed`, `shortlisted`, `rejected`, `contacted`, `hired`, `withdrawn`); `cover_note` VARCHAR(1000); `applied_at`, `viewed_at` TIMESTAMPTZ; unique (`job_id`, `applicant_id`) | `job_id` → `jobs`, `applicant_id` → `users`, `company_id` → `companies` (CASCADE); `intro_video_id` → `intro_videos`, `conversation_id` → `conversations` (SET NULL) |
| `application_events` | The history of an application's status | `from_status`, `to_status` application_status; `note` VARCHAR(500) | `application_id` → `applications` (CASCADE); `actor_id` → `users` (SET NULL) |
| `intro_videos` | A candidate's video CV (the file is in MinIO) | `object_key` VARCHAR(500), unique; `duration_sec` INTEGER; `size_bytes` BIGINT; `content_type` VARCHAR(100); `moderation_status` (`pending`, `approved`, `rejected`, `moderation_error`); `rejected_reason` TEXT; `lifecycle_status` (`loaded`, `posted`, `unposted`, `deleted`); `video_rating` (`A`, `B`, `C`); one posted video per user | `user_id` → `users` (CASCADE) |

**Chat**

| Table | Purpose | Key fields and types | Relations (on delete) |
| --- | --- | --- | --- |
| `conversations` | A chat, possibly about a job or started from an application | `type` conversation_type (`direct`, `group`, `ai`); `title` VARCHAR(150); `last_message_id` BIGINT, a copy of the newest message's id (not a foreign key, on purpose) | `job_id` → `jobs`, `application_id` → `applications` (SET NULL) |
| `conversation_participants` | Who is in a chat | `role` participant_role (`member`, `admin`, `bot`); `last_read_message_id` BIGINT (for unread counts); `is_muted` BOOLEAN; `left_at` TIMESTAMPTZ; unique (`conversation_id`, `user_id`) | `conversation_id` → `conversations`, `user_id` → `users` (CASCADE) |
| `messages` | A chat message | `content` TEXT; `status` message_status (`sent`, `delivered`, `read`); `message_type` (`text`, `system`, `ai`); `idempotency_key` VARCHAR(64), unique per conversation (a retried send is stored once); `edited_at`, `deleted_at` TIMESTAMPTZ (soft delete) | `conversation_id` → `conversations` (CASCADE); `author_id` → `users`, `reply_to_id` → `messages` (SET NULL) |

`applications.conversation_id` and `conversations.application_id` point at each other, so an application and the chat started from it can be found from either side.

**Turing Duel (the game)**

| Table | Purpose | Key fields and types | Relations (on delete) |
| --- | --- | --- | --- |
| `game_rooms` | One match | `target_size` INTEGER (players for the room); `state` game_room_state (`waiting`, `discussion`, `voting`, `finished`, `closed`); `discussion_started_at`, `voting_started_at`, `finished_at`, `room_expires_at` TIMESTAMPTZ; `bot_plan` JSONB (the bots' hidden schedule, server only) | None |
| `game_participants` | A player in a room: a person, or a bot when `user_id` is empty | `display_label` VARCHAR(20) (for example "Player 3"); `score` INTEGER; unique (`room_id`, `user_id`) | `room_id` → `game_rooms` (CASCADE); `user_id` → `users` (SET NULL) |
| `game_messages` | A chat line in a room, kept for players who reconnect | `text` TEXT; `sent_at` TIMESTAMPTZ | `room_id` → `game_rooms`, `participant_id` → `game_participants` (CASCADE) |
| `game_votes` | One player's guess about another | `guess` game_vote_guess (`bot`, `human`); one guess per voter and target, never about oneself | `room_id` → `game_rooms`, `voter_participant_id`, `target_participant_id` → `game_participants` (CASCADE) |

## Features List

<!-- TODO DOC-06 (byul-byul): complete list of implemented features, owner(s) of each, short description of each. Implemented features only. -->

## Modules

<!-- TODO DOC-06 (byul-byul): one row per chosen module, with justification and implementation notes. Add rows only for modules that work. -->

| Module | Type | Points | Owner(s) | How it was implemented |
| --- | --- | --- | --- | --- |

**Total points:** TODO DOC-06 (Major = 2, Minor = 1).

## Individual Contributions

<!-- TODO DOC-07 (Zayid): per member, what they built (features, modules, components), plus challenges faced and how they were overcome. -->

## Known limitations

<!-- TODO DOC-06 (byul-byul), filled before submission: honest list of what does not work or is missing. -->

## Credits

The animated GIF below and its generator ([tools/make_lobby.py](tools/make_lobby.py)) were added to this repository by Zayid Elkahir.

<!-- TODO DOC-07 (Zayid): confirm the author of the GIF and the license/attribution to write here. -->

![Four folders dancing in the group project lobby while actual progress stays at zero.](assets/group-project-lobby.gif)
