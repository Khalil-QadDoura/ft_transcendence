# Base images pinned by tag and multi-arch digest (INF-07, `make images-check`).

# Stage 1 (build): install the runtime packages into a virtual environment.
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install -r requirements.txt

# Stage 2 (runtime): a clean image with only that environment and our code, run as a
# non-root user. No tests, no test tools, no pip cache. Compose builds api and worker
# from this stage (`target: runtime`).
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS runtime
ENV PATH=/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /venv /venv
COPY alembic.ini docker-entrypoint.sh ./
COPY alembic ./alembic
COPY app ./app
USER app
EXPOSE 8000
CMD ["./docker-entrypoint.sh"]

# Stage 3 (test): the runtime image plus the development tools of requirements-dev.txt
# (pytest, ruff, ...). Only `make test` builds it (compose service api-test, profile test)
# and mounts the code with the tests read-only; nothing ships from here.
FROM runtime AS test
USER root
COPY requirements.txt requirements-dev.txt /tmp/requirements/
RUN PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    pip install -r /tmp/requirements/requirements-dev.txt && rm -rf /tmp/requirements
USER app
