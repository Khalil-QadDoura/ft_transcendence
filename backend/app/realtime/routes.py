"""The WebSocket layer's endpoints: POST /api/ws/ticket, then the socket itself at /ws."""

from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from redis.asyncio import Redis

from app.auth.deps import CurrentUser
from app.core.redis_client import get_redis
from app.realtime import service
from app.realtime.schemas import TicketOut

router = APIRouter(prefix="/ws", tags=["websocket"])  # mounted under /api
socket_router = APIRouter()  # mounted at the root: the proxy passes /ws to the API as it is

# This app's Redis client (app/core/redis_client.py), the way Session gives the database.
RedisClient = Annotated[Redis, Depends(get_redis)]


@router.post("/ticket")
async def create_ticket(user: CurrentUser, redis: RedisClient) -> TicketOut:
    """A one-time ticket to open the WebSocket: wss://<host>/ws?ticket=<ticket>, within 30 s.

    The access token stays in the Authorization header of this request. It never goes into
    the socket's address, where the proxy's access log would keep it."""
    return TicketOut(ticket=await service.create_ticket(redis, user))


@socket_router.websocket("/ws")
async def user_socket(websocket: WebSocket) -> None:
    """The user's live connection. Every frame is JSON {type, payload}; "ping" gets "pong"."""
    user = await service.authenticate_ws(websocket)
    if user is None:
        return  # already closed with code 1008
    await service.serve_socket(websocket, user)
