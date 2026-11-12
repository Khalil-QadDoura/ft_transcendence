"""The rules of the WebSocket layer. Routes call these functions; these call the repo."""

import asyncio
import json
import secrets
import uuid
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

import structlog
from fastapi import FastAPI, WebSocket, status
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from app.auth import repo as auth_repo
from app.realtime import repo
from app.realtime.constants import PRESENCE_TTL_SECONDS, TICKET_LIFETIME_SECONDS
from app.realtime.schemas import Event, PresenceOut
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
    if holder is None:  # never made, expired, or already used
        return None
    # A short session of our own: a socket stays open for hours, and it must not keep a
    # database connection for all that time.
    async with app.state.session_factory() as session:
        user = await auth_repo.get_user_by_id(session, holder["user_id"])
    if user is None or user.status != "active" or user.token_version != holder["token_version"]:
        return None
    return user


async def send_to_user(redis: Redis, user_id: int, event_type: str, payload: Any = None) -> None:
    """Send one event to every socket the user has open, whichever API process holds them.

    This is how other cards push a live update, for example after saving a message (BE-24):
        await send_to_user(redis, peer_id, "message", MessageOut.model_validate(message))
    A user with no open socket gets nothing; the client reloads what it shows when it reconnects.
    """
    frame = Event(type=event_type, payload=payload).model_dump_json()
    try:
        await repo.publish(redis, user_id, frame)
    except RedisError:
        # The change itself is already saved; only the live notice is lost. Log it, go on.
        log.warning("event not sent", user_id=user_id, type=event_type, exc_info=True)


async def serve_socket(websocket: WebSocket, user: User) -> None:
    """The life of one open socket, until the client goes away.

    The socket listens on its user's Redis channel, and a second task copies whatever arrives
    there to the browser, while this one reads what the browser sends. The socket is also
    written into the user's presence key: the user's friends hear when the first socket opens
    (online) and when the last one closes (offline).
    """
    app = websocket.app
    redis = app.state.redis
    socket_id = uuid.uuid4().hex  # this socket's own name in the presence key
    pubsub = redis.pubsub()  # a Redis connection only for listening
    await pubsub.subscribe(repo.user_channel(user.id))
    forwarding = asyncio.create_task(forward_events(pubsub, websocket))
    log.info("socket open", user_id=user.id)
    try:
        if await repo.add_socket(redis, user.id, socket_id, PRESENCE_TTL_SECONDS) == 1:
            await tell_friends(app, user.id, is_online=True)  # the first socket: now online
        await read_frames(websocket, redis, user.id, socket_id)
    finally:
        forwarding.cancel()
        await asyncio.wait({forwarding})  # until it has really stopped
        await pubsub.aclose()  # stop listening and give the connection back
        log.info("socket closed", user_id=user.id)
        if await repo.remove_socket(redis, user.id, socket_id) == 0:
            await tell_friends(app, user.id, is_online=False)  # the last socket: now offline


async def forward_events(pubsub: PubSub, websocket: WebSocket) -> None:
    """Copy each event that arrives on the user's channel to this socket, as it is."""
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":  # not Redis's "subscribed" confirmation
                await websocket.send_text(message["data"])
    except Exception:
        # Redis went away (or the socket did). A socket that gets no events is useless: close
        # it with 1011, so that the client reconnects and reloads what it shows.
        log.warning("event forwarding stopped", exc_info=True)
        with suppress(Exception):  # the socket may already be gone
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


async def read_frames(websocket: WebSocket, redis: Redis, user_id: int, socket_id: str) -> None:
    """Answer the client's frames until it disconnects. Only "ping" so far: it keeps the user
    online for PRESENCE_TTL_SECONDS more and gets "pong". Frames of a type this layer does not
    know (or not JSON at all) are ignored."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if frame_type(message.get("text")) == "ping":
            await repo.refresh_socket(redis, user_id, socket_id, PRESENCE_TTL_SECONDS)
            await websocket.send_text(Event(type="pong").model_dump_json())


def frame_type(text: str | None) -> str | None:
    """The type of a JSON frame such as {"type": "ping"}; None for anything else."""
    try:
        frame = json.loads(text or "")
    except ValueError:  # not JSON, or a binary frame (no text)
        return None
    return frame.get("type") if isinstance(frame, dict) else None


async def tell_friends(app: FastAPI, user_id: int, is_online: bool) -> None:
    """Send a "presence" event {user_id, is_online} to each of the user's friends."""
    async with app.state.session_factory() as session:
        friend_ids = await repo.friend_ids(session, user_id)
    presence = PresenceOut(user_id=user_id, is_online=is_online)
    for friend_id in friend_ids:
        await send_to_user(app.state.redis, friend_id, "presence", presence)


async def is_online(redis: Redis, user_id: int) -> bool:
    """Whether the user has a socket open right now, on any API process. For the is_online
    field of the friends list and the public profile (BE-22)."""
    try:
        return await repo.count_live_sockets(redis, user_id) > 0
    except RedisError:
        log.warning("presence lookup failed", user_id=user_id, exc_info=True)
        return False


async def online_user_ids(redis: Redis, user_ids: Sequence[int]) -> set[int]:
    """Return the subset of user_ids currently online via one Redis pipeline (BE-22)."""
    if not user_ids:
        return set()
    try:
        counts = await repo.count_live_sockets_many(redis, user_ids)
    except RedisError:
        log.warning("batch presence lookup failed", count=len(user_ids), exc_info=True)
        return set()
    return {uid for uid, live in counts.items() if live > 0}
