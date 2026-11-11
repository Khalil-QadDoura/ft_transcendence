"""The rules of the WebSocket layer. Routes call these functions; these call the repo."""

import json
import secrets

import structlog
from fastapi import FastAPI, WebSocket, status
from redis.asyncio import Redis

from app.auth import repo as auth_repo
from app.realtime import repo
from app.realtime.constants import TICKET_LIFETIME_SECONDS
from app.realtime.schemas import Event
from app.users.models import User

INVALID_TICKET = "Invalid or expired ticket"

log = structlog.get_logger(__name__)


async def create_ticket(redis: Redis, user: User) -> str:
    """A new one-time ticket for this user, kept in Redis for TICKET_LIFETIME_SECONDS."""
    ticket = secrets.token_urlsafe(32)  # 43 random characters: nobody can guess one
    # The token_version is kept with it: a password change before the socket opens makes
    # the ticket useless, like every token made before it.
    await repo.save_ticket(redis, ticket, user.id, user.token_version, TICKET_LIFETIME_SECONDS)
    return ticket


async def authenticate_ws(websocket: WebSocket) -> User | None:
    """The login check of every WebSocket route (/ws, and /ws/game in BE-09).

    Reads the one-time ticket from the address (?ticket=...) and returns its user. Otherwise
    it closes the socket with code 1008 and returns None: no ticket, an unknown, expired or used
    ticket, a deleted user, or a password changed since the ticket was made (token_version).

    The socket is accepted before the check on purpose. Closed before that, the browser would
    only see a failed connection (code 1006), not the 1008 that says "get a new ticket".
    """
    await websocket.accept()
    user = await user_for_ticket(websocket.app, websocket.query_params.get("ticket", ""))
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=INVALID_TICKET)
    return user


async def user_for_ticket(app: FastAPI, ticket: str) -> User | None:
    """The active user a ticket belongs to, using the ticket up; None if it opens nothing."""
    if not ticket:
        return None
    holder = await repo.take_ticket(app.state.redis, ticket)
    if holder is None:  # never made, older than 30 s, or already used
        return None
    # A short session of our own: a socket stays open for hours, and it must not keep a
    # database connection for all that time.
    async with app.state.session_factory() as session:
        user = await auth_repo.get_user_by_id(session, holder["user_id"])
    if user is None or user.status != "active" or user.token_version != holder["token_version"]:
        return None
    return user


async def serve_socket(websocket: WebSocket, user: User) -> None:
    """The life of one open socket, until the client goes away."""
    log.info("socket open", user_id=user.id)
    try:
        await read_frames(websocket)
    finally:
        log.info("socket closed", user_id=user.id)


async def read_frames(websocket: WebSocket) -> None:
    """Answer the client's frames until it disconnects. Only "ping" so far; frames of a type
    this layer does not know (or not JSON at all) are ignored."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if frame_type(message.get("text")) == "ping":
            await websocket.send_text(Event(type="pong").model_dump_json())


def frame_type(text: str | None) -> str | None:
    """The type of a JSON frame such as {"type": "ping"}; None for anything else."""
    try:
        frame = json.loads(text or "")
    except ValueError:  # not JSON, or a binary frame (no text)
        return None
    return frame.get("type") if isinstance(frame, dict) else None
