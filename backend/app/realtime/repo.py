"""Queries of the WebSocket layer: Redis commands, and the friends it tells about presence.
No HTTP, no rules.

Every Redis key this layer makes starts with "ws:", so it is easy to find in Redis.
"""

import json
import time

from redis.asyncio import Redis
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.friends.models import Friendship


def ticket_key(ticket: str) -> str:
    return f"ws:ticket:{ticket}"


async def save_ticket(
    redis: Redis, ticket: str, user_id: int, token_version: int, lifetime_seconds: int
) -> None:
    """Keep the ticket with the user it belongs to. `ex` makes Redis delete it by itself once
    `lifetime_seconds` have passed."""
    holder = json.dumps({"user_id": user_id, "token_version": token_version})
    await redis.set(ticket_key(ticket), holder, ex=lifetime_seconds)


async def take_ticket(redis: Redis, ticket: str) -> dict | None:
    """Read the ticket and delete it, as one Redis step (GETDEL), so it works only once: if
    the same ticket comes twice at the same moment, only one of them gets it.

    Returns {"user_id", "token_version"}, or None for an unknown, expired or used ticket.
    """
    holder = await redis.getdel(ticket_key(ticket))
    return json.loads(holder) if holder is not None else None


def user_channel(user_id: int) -> str:
    """The pub/sub channel of one user: every socket of that user listens on it."""
    return f"ws:user:{user_id}"


async def publish(redis: Redis, user_id: int, frame: str) -> None:
    """Hand the frame to every socket listening on the user's channel, on any API process.
    Redis keeps nothing: a socket that is not listening right now never gets it."""
    await redis.publish(user_channel(user_id), frame)


# Presence. Each user has one key: a sorted set of the user's open sockets, each with a score =
# the time (in seconds) until which that socket counts as online. "ping" moves it forward. The
# whole key also expires when nobody pinged for a while, so a crashed API leaves nothing behind.


def presence_key(user_id: int) -> str:
    return f"ws:presence:{user_id}"


async def add_socket(redis: Redis, user_id: int, socket_id: str, ttl_seconds: int) -> int:
    """Write this socket into the user's presence key, online for `ttl_seconds`. Returns how
    many live sockets the user has now: 1 means this one is the first.

    The steps run as one transaction (MULTI ... EXEC): two sockets opening at the same moment on
    two API workers cannot both count as the first."""
    key = presence_key(user_id)
    now = time.time()
    async with redis.pipeline(transaction=True) as steps:
        steps.zremrangebyscore(key, "-inf", now)  # forget sockets whose time ran out
        steps.zadd(key, {socket_id: now + ttl_seconds})
        steps.expire(key, ttl_seconds)
        steps.zcard(key)  # how many are left
        *_, live = await steps.execute()
    return live


async def refresh_socket(redis: Redis, user_id: int, socket_id: str, ttl_seconds: int) -> None:
    """On "ping": this socket stays online for `ttl_seconds` more, and so does the key."""
    key = presence_key(user_id)
    async with redis.pipeline(transaction=True) as steps:
        steps.zadd(key, {socket_id: time.time() + ttl_seconds})
        steps.expire(key, ttl_seconds)
        await steps.execute()


async def remove_socket(redis: Redis, user_id: int, socket_id: str) -> int:
    """Take this socket out of the user's presence key. Returns how many live sockets are
    left: 0 means it was the last one. One transaction, like add_socket()."""
    key = presence_key(user_id)
    async with redis.pipeline(transaction=True) as steps:
        steps.zrem(key, socket_id)
        steps.zremrangebyscore(key, "-inf", time.time())
        steps.zcard(key)
        *_, live = await steps.execute()
    return live


async def count_live_sockets(redis: Redis, user_id: int) -> int:
    """How many of the user's sockets still count as online right now."""
    return await redis.zcount(presence_key(user_id), time.time(), "+inf")


async def friend_ids(session: AsyncSession, user_id: int) -> list[int]:
    """The ids of the user's friends: the other side of every accepted friendship (the user
    may have sent the request or received it)."""
    other_side = case(
        (Friendship.requester_id == user_id, Friendship.addressee_id),
        else_=Friendship.requester_id,
    )
    rows = await session.scalars(
        select(other_side).where(
            Friendship.status == "accepted",
            or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
        )
    )
    return list(rows)
