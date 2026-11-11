"""Realtime WebSocket event broadcaster and connection manager."""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active local WebSocket connections and Redis pub/sub distribution.

    Works in single-process mode and multi-worker mode with Redis pub/sub.
    If Redis is unreachable or offline, operations gracefully fallback to local-only.
    """

    def __init__(self) -> None:
        self._local: dict[int, set[WebSocket]] = defaultdict(set)
        self._redis: Any = None

    def _get_redis(self) -> Any:
        if self._redis is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(redis_url, decode_responses=True)
            except Exception as exc:
                logger.debug("Redis connection initialization skipped: %s", exc)
                return None
        return self._redis

    @staticmethod
    def _channel(user_id: int) -> str:
        return f"ws:user:{user_id}"

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self._local[user_id].add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        self._local[user_id].discard(ws)
        if not self._local[user_id]:
            del self._local[user_id]

    def is_online(self, user_id: int) -> bool:
        return bool(self._local.get(user_id))

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

    async def send_to_user(self, user_id: int, data: dict[str, Any]) -> None:
        """Deliver data to a user via Redis pub/sub and local connections."""
        # 1. Send to local WebSockets if any exist in this process
        local_sockets = list(self._local.get(user_id, set()))
        for ws in local_sockets:
            if ws.client_state == WebSocketState.CONNECTED:
                try:
                    await ws.send_json(data)
                except Exception:
                    pass

        # 2. Publish to Redis for other worker processes
        try:
            r = self._get_redis()
            if r is not None:
                await r.publish(self._channel(user_id), json.dumps(data))
        except Exception as exc:
            logger.debug("Redis publish skipped for user %s: %s", user_id, exc)


manager = ConnectionManager()
