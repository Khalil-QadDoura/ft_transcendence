"""Response shapes of the health endpoints (they also appear in /api/openapi.json)."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthComponentsOut(BaseModel):
    """Health status of each component. No hostnames, versions or secrets."""

    db: Literal["ok", "down"] = Field(description="PostgreSQL connectivity")
    redis: Literal["ok", "down"] = Field(description="Redis cache and pub/sub connectivity")
    minio: Literal["ok", "down"] = Field(description="MinIO object storage connectivity")
    worker: Literal["ok", "down"] = Field(description="Celery background moderation worker")


class HealthOut(BaseModel):
    """Overall service health status and per-component breakdown (BE-31 / M14)."""

    status: Literal["ok", "degraded", "down"] = Field(
        description=(
            "Overall service health: ok when all components are up, "
            "degraded if worker or minio are down, down if db or redis are down."
        )
    )
    components: HealthComponentsOut


class DatabaseHealthOut(BaseModel):
    """Internal database health check response for /_internal/health/db."""

    database: Literal["ok", "unreachable"]
