# WOZU web workspace

A responsive React frontend connected to the working WOZU FastAPI reference backend. This branch contains the web application and an isolated development harness. It does **not** replace the team's planned backend or merge the reference repository into this repository.

## Run the frontend

Use Node 22.12+ (tested with the installed Node runtime), then:

```sh
cd frontend
npm ci
cp .env.example .env
npm run dev
```

Open http://127.0.0.1:5173. Vite forwards `/api` to `127.0.0.1:8000`, removes the prefix for the reference backend, and proxies both WebSocket routes. Keep the browser on one hostname so tab sessions and storage stay consistent. `npm run build` produces `dist/`; production hosting must provide SPA fallbacks and equivalent HTTPS API/WebSocket proxying.

## Run the reference backend separately

Reference source: [byul-byul/ft_transcendence](https://github.com/byul-byul/ft_transcendence), pinned to `adcee1b90bec967fd2a4fce20bc6564a488db2a6`. Original backend authorship stays with that repository. `scripts/reference-web.patch` contains the narrow compatibility changes made for this frontend; inspect that patch before integrating anything into the team's backend.

The following setup targets Ubuntu 24.04 / WSL2. Commands below run from `frontend/` inside Linux. Setup creates only the `wozu_frontend_dev` database and role; it does not reset existing databases. Its generated secrets and reference checkout live under ignored `.local/`.

```sh
sudo apt-get update
sudo apt-get install -y git python3-venv postgresql postgresql-16-postgis-3 redis-server ffmpeg golang-go
sudo service postgresql start
python3 scripts/reference-dev.py setup
mkdir -p .local/bin
GOBIN="$PWD/.local/bin" GOTOOLCHAIN=auto go install github.com/minio/minio@v0.0.0-20260212201848-7aac2a2c5b7c
```

MinIO is built from its [official source](https://github.com/minio/minio), because the old binary/image downloads used by the reference setup are unavailable. The first build can take several minutes. Go may download the required Go toolchain automatically. This local storage service is for development.

Start each service in its own terminal:

```sh
python3 scripts/reference-dev.py redis
python3 scripts/reference-dev.py minio
python3 scripts/reference-dev.py api
```

Then, once the services are running:

```sh
python3 scripts/reference-dev.py seed
python3 scripts/reference-dev.py seed-media
```

The fixtures are fictional local data: six companies/jobs, a candidate, a friend, a conversation, and an explicitly approved sample MP4. **The sample video's approval is a fixture, not an AI moderation result.** Both seed scripts refuse non-demo databases. No fixture is automatically created on application startup.

| Role      | Email                 | Password      |
| --------- | --------------------- | ------------- |
| Candidate | candidate@example.com | WozuDemo!2026 |
| Employer  | employer@example.com  | WozuDemo!2026 |
| Friend    | friend@example.com    | WozuDemo!2026 |

These credentials are for the isolated local demo only. Never use them in a shared deployment. Existing checkout locations can be supplied through `WOZU_REFERENCE_REPO`, `WOZU_REFERENCE_ENV`, `WOZU_REFERENCE_VENV`, and `WOZU_REFERENCE_MINIO`.

New uploads are persisted as pending. To enable real moderation, configure `OPENAI_API_KEY` in the private reference environment and run `python3 scripts/reference-dev.py worker`. Keep `MODERATION_FAIL_OPEN=false`. Real email delivery also needs the reference backend's Brevo configuration. `FRONTEND_BASE_URL=http://localhost:5173` routes verification/reset email links into the web interface. No paid provider has been invoked for this implementation.

## Implemented journeys

- Email sign-in, registration/verification screens, password recovery/change, token rotation and protected routes.
- Job discovery with keyword/salary/schedule/urgency filters, pagination, device-local bookmarks, details, video applications and application tracking.
- Own/public profiles, avatar uploads, incoming friend requests, connections and direct conversations.
- Chat with history pagination, idempotent sending, editing, deletion, unread counts and WebSocket invalidation.
- Video studio with local previews, MP4 upload/progress, supported-browser recording, moderation states, publishing and feed.
- Employer company setup, job creation/editing/deletion, real totals, candidate review, introduction playback and application transitions.
- Turing Duel matchmaking, chat, server phase countdowns, persistent reconnect history/votes and results.
- Responsive navigation, Arabic RTL layout, reduced-motion styling, keyboard focus states, loading/empty/error states and development legal/status pages.

## Reference compatibility patch

The patch adds authenticated room snapshots (self ID, deadlines, recent messages, own votes), room IDs on game events, same-room vote validation, game socket token-version validation, signed avatar URLs with confirmation ownership checks, authorized application-video playback, frontend email URLs, and a migration for the moderation error state already used by the worker. It pins [Kombu 5.3.7](https://pypi.org/project/kombu/5.3.7/) to match the reference's Redis 5/Celery 5.3 dependencies; the currently resolved newer transport rejected Redis 5 at runtime.

The original API schema stays in `docs/api/wozu-reference-openapi.json`; optional web support response fields are typed at their integration points. When the team's backend is ready, update the schema, run `npm run gen:api`, and adapt the API boundary. `VITE_BACKEND_MODE=team` selects ticket-based WebSocket URLs, but that future backend mode has not been integration-tested. Changing a prefix alone does not guarantee contract compatibility.

## Validation

```sh
npm run typecheck
npm run lint
npm test
npm run build
npm run format:check
python3 scripts/reference-dev.py check
```

The integration check only permits the isolated demo database. It exercises auth/refresh, unauthorized requests, profile updates, discovery, application ownership/duplicates, employer transitions, chat idempotency/edit/delete, signed media upload/playback/CORS, publication guards, and a complete real server-timed game. It creates local test records and takes about three minutes. The candidate's sample application advances to `contacted` and remains available for reviewing employer messaging.

## Remaining release work

- Configure and verify real email and AI moderation providers. Camera capture depends on browser MP4 MediaRecorder support; unsupported browsers can upload MP4 files.
- Review translations with native speakers. English is complete; Arabic/Azerbaijani/Turkish/Russian currently have translated navigation and selected screens with English fallback, not complete localization.
- Add map discovery, advanced board-specific lobby/tournament requirements, friendship removal and any other requirements absent from the reference API/UI. This branch is not a declaration that all 97 board cards are complete.
- Replace draft privacy/terms copy with approved text and review accessibility with assistive technology.
- Audit the older reference backend and dependencies before public deployment, configure secure hosting, and run the team's CI/subject acceptance tests. Saved jobs are device-local, not synchronized server records.

## Design and provenance

The visual system uses warm ivory, near-black, vivid coral and a restrained chartreuse accent for Turing Duel. Manrope/DM Sans typography pairs with italic editorial headlines and an original animated SVG orbital sculpture. Fonts and artwork are bundled locally; motion respects the reduced-motion preference. `src/identity.css` owns the shared visual identity and responsive refinements, while `src/index.css` provides feature layouts. The game room shows server-controlled phases, remaining time and real participant results. There are no external stock-image requests or fabricated live statistics. AI-assisted implementation is recorded in this branch's real commits; no dates or historical activity are fabricated.
