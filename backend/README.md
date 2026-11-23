# Backend

FastAPI + SQLAlchemy 2 (async) + Alembic + Redis, Python 3.11. Every route lives under `/api`; the WebSocket lives at `/ws`.

## Layout

```
app/
  main.py        app factory: settings, logging, middleware, error handlers, routers, lifespan
  core/          config (env), errors, logging (JSON), limiter and limits (every rate limit, BE-12),
                 request_id, internal (/_internal guard),
                 mailer (SMTP, or Brevo's API when BREVO_API_KEY is set),
                 redis_client (each app's Redis client, get_redis),
                 storage (MinIO: signed links, file checks, public picture addresses),
                 metrics (Prometheus /metrics and ws_connections gauge, BE-30),
                 queue (Celery tasks on Redis)
  db/            base (Base + naming convention), session (each app's engine, get_session),
                 mixins (TimestampMixin, AuditMixin), models (imports every table model)
  health/        GET /api/health with per-component checks (db, redis, minio, worker)
                 and the internal database check (BE-31)
  auth/          /api/auth: register, verify, login, refresh, logout (BE-03), change-password,
                 forgot-password, reset-password (BE-04), oauth/42/start and oauth/42/callback
                 (BE-11), plus constants (lifetimes, OAuth), security (Argon2id, JWT, reset
                 tokens, OAuth state), deps (get_current_user), oauth42 (the 42 intra API client)
  users/         /api/users/me: read, partial update, soft delete (BE-05), avatar_url (BE-08),
                 plus constants (minimum age, field lengths)
  companies/     CRUD, /companies/me returns 200 null for job seekers (BE-21)
  friends/       friend requests, single-query friends list, /users/{id}/profile with
                 avatar_url and online status (BE-22)
  jobs/          CRUD, /jobs/mine counters, draft vs open visibility (BE-25)
  realtime/      POST /api/ws/ticket and the WebSocket at /ws (BE-06, BE-24): one-time tickets,
                 authenticate_ws(), send_to_user() through Redis pub/sub, presence in Redis,
                 delivered / read frames, plus constants (ticket lifetime, presence TTL)
  media/         /api/media: intro video upload-url, confirm, mine, post, unpost, delete,
                 feed (BE-07); avatar and company logo upload-url and confirm, the default
                 avatar picture (BE-08); plus constants (video and picture limits, link lifetimes)
  worker/        celery_app: the Celery app of the worker container (its tasks come with BE-29)
  conversations/ direct chats, participants, idempotent messages, edits/deletes, read state (BE-23, BE-24)
  game/          /api/game: Redis-locked matchmaking queue, waiting room lifecycle, start now,
                 hidden random bot plan, staggered joins, template bot chat and server phases (BE-27);
                 votes by label number, scoring when voting ends and results (BE-10), plus
                 scoring.py (the points, win / draw / loss and deception rate rules, no database)
                 chat.py: the room socket /ws/game, room chat and its history, the snapshot
                 sent on every (re)connect (BE-09)
  applications/  only models.py so far (BE-02); each feature card adds its other four files
  <domain>/      every domain package has the same five files:
    models.py      SQLAlchemy tables
    schemas.py     Pydantic request / response shapes
    repo.py        database queries only, no HTTP
    service.py     business rules
    routes.py      thin FastAPI router
alembic/         migrations: one initial migration creates the 17 tables (BE-02)
tests/           pytest, one file per area
```

A new domain router is added in `create_app()` with `api.include_router(...)`, so it lands under `/api` automatically.

## Run locally

```sh
cd backend
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then point DATABASE_URL at a running PostgreSQL
                                # and set JWT_SECRET (openssl rand -hex 32)
alembic upgrade head
uvicorn app.main:app --reload   # http://localhost:8000/api/docs when ENV=dev
```

## Checks

```sh
pytest -q                          # no database needed: the database tests are skipped
ruff check . && ruff format --check .
docker build -t wozu-backend .     # runtime image only: no tests, no test tools
```

The database tests (`tests/test_schema.py`, `tests/test_auth.py`, `tests/test_password.py`,
`tests/test_users.py`, `tests/test_media.py`, `tests/test_pictures.py`) need an empty PostgreSQL
with PostGIS. They delete every table (schema) or every user (auth, password, users, media,
pictures), so they only use `TEST_DATABASE_URL`, and only if its database name contains `test`:

```sh
docker run -d --name wozu-test-db -p 5432:5432 -e POSTGRES_PASSWORD=test \
    -e POSTGRES_DB=wozu_test postgis/postgis:15-3.4
TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:5432/wozu_test pytest -q
```

The WebSocket tests (`tests/test_realtime.py`) also need a Redis. They start the API with uvicorn
on a free port (twice, to act as two API workers) and connect with a real WebSocket client. They
use only `TEST_REDIS_URL` and delete only the keys they make (names starting with `ws:`):

```sh
docker run -d --name wozu-test-redis -p 6379:6379 redis:7-alpine
TEST_DATABASE_URL=... TEST_REDIS_URL=redis://localhost:6379/1 pytest -q
```

The security tests (`tests/test_security_routes.py`, `test_security_access.py`,
`test_security_inputs.py`, BE-13) need the database and a Redis too: every route's login check,
one user against another's data, and hostile input on every route and socket.

The login with 42 tests (`tests/test_oauth42.py`) need the database and a Redis too. They never
contact 42: each test starts a small fake 42 (an HTTP server on a free local port) and points
`FT_AUTHORIZE_URL`, `FT_TOKEN_URL` and `FT_ME_URL` at it. They delete only the Redis keys they
make (names starting with `oauth42:state:`).

The media tests also need a MinIO and a Redis, again only through `TEST_*` variables (they empty
the `media-test` bucket and the `celery` queue); the docstring of `tests/test_media.py` shows the
two `docker run` lines. Without `TEST_MINIO_ENDPOINT`, `TEST_MINIO_ACCESS_KEY`,
`TEST_MINIO_SECRET_KEY` and `TEST_REDIS_URL` they are skipped. The avatar and logo tests
(`tests/test_pictures.py`) need the same MinIO but no Redis; they empty the `pictures-test`
bucket and give it the anonymous policy of `minio-init` (download under `avatars/` and
`logos/`).

## Conventions

- **Errors** always look like `{"error": {"code": "<status>", "detail": ...}}`. Raise `HTTPException(status_code, detail)`; validation errors report only the first failing field, e.g. `"body → email: Field required"`.
- **Text input**: a NUL character anywhere in the query or the JSON body is a 422 before the route runs (`refuse_nul` on the `/api` router, `app/core/inputs.py`), because PostgreSQL cannot store it. Every id in a path, a query or a body takes `ge=1, le=MAX_ID` (2^63−1), and every text field that is saved a `max_length`.
- **Request id**: every response has an `x-request-id` header, and every log line of that request carries the same `request_id`.
- **Rate limits** (numbers in `app/core/limits.py`): every POST, PUT, PATCH and DELETE under `/api` is limited without a word from the route (`limit_writes` on the `/api` router): per route, per user with a valid access token, else per client IP. A route gets its own number with one line in `ROUTE_RATE_LIMITS`. Login and sign-up also count per IP with `@limiter.limit(LOGIN_RATE_LIMIT)` and a `request: Request` argument on the route. The client IP comes from the `X-Real-IP` header the proxy sets (the direct connection's IP when there is no proxy). Over a limit → 429 with the error body and `Retry-After`.
- **Login check**: a route that needs a logged-in user takes `user: CurrentUser` (from `app.auth.deps`). It answers 401 when the `Authorization: Bearer` token is missing, wrong, expired, or older than the user's `token_version`. Token lifetimes are in `app/auth/constants.py`, the auth rate limits in `app/core/limits.py`. A route meant for visitors goes into `PUBLIC` in `tests/test_security_routes.py`, with the reason: that test fails for any route that has neither a login check nor a line there (BE-13).
- **Answers**: a route returns its `...Out` schema, e.g. `VideoStatusOut.model_validate(video)` or `users.service.to_user_out(storage, user)`, never the table model, so only the fields listed in the schema leave the server (never `password_hash` or `token_version`).
- **Partial updates (PATCH)**: every field of the request schema has a default and the schema has `extra="forbid"`; the service applies only `data.model_dump(exclude_unset=True)`. A field that is not sent keeps its value, and an unknown field gets 422 (see `app/users/`).
- **Email**: a route takes `mailer: Annotated[Mailer, Depends(get_mailer)]` and sends with `background.add_task(mailer.send, to, subject, body)`, so the answer does not wait for the mail server; a failed send is logged. Tests replace `get_mailer` with a fake; the `smtp_server` fixture in `tests/conftest.py` is a real SMTP server for tests that send through the real mailer. Locally, emails land in Mailpit (INF-05) at `https://localhost/mail`.
- **Files** never pass through the API: a route returns a link signed for `MINIO_EXTERNAL_ENDPOINT`, the browser PUTs the file there, then a `confirm` route checks the file in storage itself (`Storage.stat`, `Storage.first_bytes`, `Storage.read` from `app.core.storage`). MinIO calls wait for the network, so routes run them with `asyncio.to_thread`.
- **Pictures are public, videos are not**: anyone may download the files under `avatars/` and `logos/` (the bucket policy of `minio-init`, INF-04), so a response gives their plain address, `Storage.avatar_url(key)` (the default picture when the key is empty) or `Storage.logo_url(key)`, never a signed link. Every other file (intro videos) is private and only reached with a signed link. Because those folders are public, no upload link ever points into them: the browser uploads a picture into the private `staging/` folder, `confirm` checks it (Pillow decodes it) and the API writes the public copy itself (`Storage.put`). A route that replaces or forgets a picture deletes its old file (`remove_files` from `app.core.storage`).
- **Background tasks for the worker**: a route takes `queue: Annotated[TaskQueue, Depends(get_queue)]` and runs `background.add_task(queue.moderate_video, ...)`: the task lands on the Redis queue after the answer, and a failure is logged (like the emails).
- **Live events**: to push something to a user's open sockets (every tab, on every API worker), a
  route takes `redis: RedisClient` (see `app/realtime/routes.py`) and, after the commit, calls
  `await send_to_user(redis, user_id, "event_type", payload)` from `app.realtime.service`; the
  socket gets `{"type": "event_type", "payload": ...}`. `payload` can be a dict or an `...Out`
  schema. A user with no open socket gets nothing, so the data must already be saved. A socket
  route checks its user with `authenticate_ws(websocket)` (one-time ticket, close code 1008).
  Who is online: `await is_online(redis, user_id)`. Redis keys of the WebSocket layer start with `ws:`.
- **Internal routes** go under `/_internal`. They are left out of the OpenAPI spec and answer 404 unless the `X-Internal-Key` header matches `INTERNAL_API_KEY`; the proxy also blocks them.
- **OpenAPI** is at `/api/openapi.json` (the frontend generates its types from it); Swagger UI is at `/api/docs` only when `ENV=dev`.
- **Migrations** run on container start (`alembic upgrade head` in `docker-entrypoint.sh`).
  A schema change is a new migration (`alembic revision --autogenerate -m "..."`, then read and
  tidy it); never edit one that has already run somewhere. A new models module is imported in
  `app/db/models.py`. `alembic check` says whether the models and the database still agree.
- **Tables:** ids are `bigint`; every table has `created_at` / `updated_at` (`TimestampMixin`);
  every foreign key column has an index (PostgreSQL does not add one by itself) unless a unique
  constraint already starts with it; users, companies, jobs and videos are never removed, only
  set to a `deleted` status. Fixed value lists are PostgreSQL enum types; adding a value needs a
  migration (`ALTER TYPE ... ADD VALUE`). The jobs search trigger exists only in the migration, so
  a database is always built with Alembic, never with `Base.metadata.create_all()`.


## Transactional test fixtures (BE-20)

`db` and `async_db_client` require an explicit `TEST_DATABASE_URL` whose database
name contains `test`. They never fall back to the application's `DATABASE_URL`.
Use only a disposable test database: the existing schema/auth suites still drop
or truncate their own data. A skipped database suite is not a successful database check.

`db` binds an AsyncSession to an outer transaction with `join_transaction_mode="create_savepoint"`.
Services can call real `commit()` and `rollback()`; test teardown rolls back the outer
transaction. This follows SQLAlchemy's external-transaction testing recipe:
https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites
A test needing application tables must run Alembic first; do not use `create_all()`.

`async_client` covers database-free ASGI routes. `async_db_client` overrides `get_session`
with the test's `db` session, so setup queries and requests share one isolated transaction.
Route-test apps made with `build_app()` use a recording mailbox via `get_mailer`;
SMTP/Brevo adapter tests still exercise the real Mailer with their explicit local fakes.
There are no MinIO or Celery mocks: `tests/test_media.py` uses a real MinIO and Redis, and
`tests/test_pictures.py` a real MinIO (one test makes its deletes fail on purpose, one slows a read down).

The backend CI job provisions PostgreSQL 15 + PostGIS, Redis and MinIO, runs lint/format checks and the
complete backend suite, and fails if any test is skipped. This provides BE-20 evidence;
INF-06 still owns the full stack checks and repository protection settings.

November 9 review integration: Nader's BE-20 branch was merged with current main,
retaining the existing schema/auth/user tests. Codex assisted Zayid with conflict
resolution, database isolation corrections, regression tests and the CI job.
