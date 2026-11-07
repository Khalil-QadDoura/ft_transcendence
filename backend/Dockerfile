# Stage 1 (build): install the runtime packages into a virtual environment.
FROM python:3.11-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install -r requirements.txt

# Stage 2 (runtime): a clean image with only that environment and our code.
# No tests, no test tools, no pip cache.
FROM python:3.11-slim
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
