"""Redis commands of the WebSocket layer. No HTTP, no rules.

Every key this layer makes starts with "ws:", so it is easy to find in Redis.
"""

import json

from redis.asyncio import Redis


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
