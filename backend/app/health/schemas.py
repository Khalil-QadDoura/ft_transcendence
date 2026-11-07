"""Response shapes of the health endpoints (they also appear in /api/openapi.json)."""

from typing import Literal

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: Literal["ok"]


class DatabaseHealthOut(BaseModel):
    database: Literal["ok", "unreachable"]
