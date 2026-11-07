# Backend

FastAPI + SQLAlchemy 2 (async) + Alembic, Python 3.11. Every route lives under `/api`; WebSockets will live under `/ws`.

## Layout

```
app/
  main.py        app factory: settings, logging, middleware, error handlers, routers, lifespan
  core/          config (env), errors, logging (JSON), limiter, request_id, internal (/_internal guard)
  db/            base (Base + naming convention), session (each app's engine, get_session),
                 mixins (TimestampMixin, AuditMixin)
  health/        GET /api/health and the internal database check
  users/ auth/ friends/ companies/ jobs/ media/ conversations/ applications/ game/
                 only models.py so far (BE-02); each feature card adds its other four files
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
alembic upgrade head
uvicorn app.main:app --reload   # http://localhost:8000/api/docs when ENV=dev
```

## Checks

```sh
pytest -q                          # no database needed: the schema tests are skipped
ruff check . && ruff format --check .
docker build -t wozu-backend .     # runtime image only: no tests, no test tools
```

The schema tests (`tests/test_schema.py`) need an empty PostgreSQL with PostGIS. They run
`alembic downgrade base`, which deletes every table, so they only use `TEST_DATABASE_URL`, and
only if its database name contains `test`:

```sh
docker run -d --name wozu-test-db -p 5432:5432 -e POSTGRES_PASSWORD=test \
    -e POSTGRES_DB=wozu_test postgis/postgis:15-3.4
TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:5432/wozu_test pytest -q
```

## Conventions

- **Errors** always look like `{"error": {"code": "<status>", "detail": ...}}`. Raise `HTTPException(status_code, detail)`; validation errors report only the first failing field, e.g. `"body → email: Field required"`.
- **Request id**: every response has an `x-request-id` header, and every log line of that request carries the same `request_id`.
- **Rate limits** are opt-in per route: `@limiter.limit("5/minute")` from `app.core.limiter`, with a `request: Request` argument on the route. Limits count per client IP, taken from the `X-Real-IP` header the proxy sets (the direct connection's IP when there is no proxy). Over the limit → 429 with the error body.
- **Internal routes** go under `/_internal`. They are left out of the OpenAPI spec and answer 404 unless the `X-Internal-Key` header matches `INTERNAL_API_KEY`; the proxy also blocks them.
- **OpenAPI** is at `/api/openapi.json` (the frontend generates its types from it); Swagger UI is at `/api/docs` only when `ENV=dev`.
- **Migrations** run on container start (`alembic upgrade head` in `docker-entrypoint.sh`).
  A schema change is a new migration (`alembic revision --autogenerate -m "..."`, then read and
  tidy it); never edit one that has already run somewhere. A new models module is imported in
  `alembic/env.py`. `alembic check` says whether the models and the database still agree.
- **Tables:** ids are `bigint`; every table has `created_at` / `updated_at` (`TimestampMixin`);
  every foreign key column has an index (PostgreSQL does not add one by itself) unless a unique
  constraint already starts with it; users, companies, jobs and videos are never removed, only
  set to a `deleted` status. Fixed value lists are PostgreSQL enum types; adding a value needs a
  migration (`ALTER TYPE ... ADD VALUE`). The jobs search trigger exists only in the migration, so
  a database is always built with Alembic, never with `Base.metadata.create_all()`.
