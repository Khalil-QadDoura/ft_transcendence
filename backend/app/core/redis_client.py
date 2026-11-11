"""Redis connection: one client per app, like the database engine (app/db/session.py)."""

from fastapi import FastAPI, Request
from redis.asyncio import Redis

from app.core.config import Settings


def setup_redis(app: FastAPI, settings: Settings) -> None:
    """Give this app its own Redis client, built from its own settings. The client keeps a pool
    of connections and connects only when a command first runs. decode_responses=True: Redis
    answers with text (str) instead of bytes."""
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis(request: Request) -> Redis:
    """FastAPI dependency: this app's Redis client."""
    return request.app.state.redis
