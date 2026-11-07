#!/bin/sh
# Container start: bring the database schema up to date, then serve the API.
set -e

alembic upgrade head

# --proxy-headers: trust X-Forwarded-For from the proxy, the only thing that can reach
# this container, so the rate limiter sees each browser's IP instead of the proxy's.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'
