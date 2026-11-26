#!/bin/sh
# Container start: bring the database schema up to date, then serve the API.
set -e

alembic upgrade head

# No uvicorn access line (query included): the app logs each request itself, path without query (QA-01).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
