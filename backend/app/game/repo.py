"""Database queries and Redis distributed locks for Turing Duel matchmaking and rooms."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import LockError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game.constants import (
    LOCK_BLOCKING_TIMEOUT_SECONDS,
    LOCK_TTL_SECONDS,
    MATCHMAKING_LOCK_KEY,
    MAX_PARTICIPANTS,
    ROOM_LOCK_KEY_PREFIX,
)
from app.game.models import GameMessage, GameParticipant, GameRoom


@asynccontextmanager
async def distributed_lock(
    redis: Redis,
    key: str,
    *,
    blocking_timeout: float = LOCK_BLOCKING_TIMEOUT_SECONDS,
) -> AsyncIterator[None]:
    """Coordinate critical sections across API workers using a Redis lock."""
    lock = redis.lock(
        key,
        timeout=LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
    )
    acquired = await lock.acquire()
    if not acquired:
        raise TimeoutError(f"Could not acquire Redis lock: {key}")
    try:
        yield
    finally:
        with suppress(LockError):
            await lock.release()


def matchmaking_lock(redis: Redis):
    return distributed_lock(redis, MATCHMAKING_LOCK_KEY)


def room_lock(
    redis: Redis, room_id: int, *, blocking_timeout: float = LOCK_BLOCKING_TIMEOUT_SECONDS
):
    return distributed_lock(
        redis, f"{ROOM_LOCK_KEY_PREFIX}{room_id}", blocking_timeout=blocking_timeout
    )


async def get_user_active_membership(
    session: AsyncSession, user_id: int
) -> tuple[GameRoom, GameParticipant] | None:
    """Return the user's open (waiting/discussion/voting) room and seat, if any."""
    stmt = (
        select(GameRoom, GameParticipant)
        .join(GameParticipant, GameParticipant.room_id == GameRoom.id)
        .where(
            GameParticipant.user_id == user_id,
            GameRoom.state.in_(("waiting", "discussion", "voting")),
        )
        .order_by(GameRoom.id.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    return (row[0], row[1]) if row is not None else None


async def find_oldest_open_waiting_room(session: AsyncSession, now: datetime) -> GameRoom | None:
    """Return the oldest unexpired waiting room with fewer than MAX_PARTICIPANTS seats.

    Note: callers acquire ``room_lock`` BEFORE ``get_room_for_update`` so Redis and Postgres row
    locks are always taken in the same order across endpoints and background ticks.
    """
    participant_count = (
        select(func.count(GameParticipant.id))
        .where(GameParticipant.room_id == GameRoom.id)
        .correlate(GameRoom)
        .scalar_subquery()
    )
    stmt = (
        select(GameRoom)
        .where(
            GameRoom.state == "waiting",
            or_(GameRoom.room_expires_at.is_(None), GameRoom.room_expires_at > now),
            participant_count < MAX_PARTICIPANTS,
        )
        .order_by(GameRoom.created_at.asc(), GameRoom.id.asc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def get_room(session: AsyncSession, room_id: int) -> GameRoom | None:
    return await session.scalar(select(GameRoom).where(GameRoom.id == room_id))


async def get_room_for_update(session: AsyncSession, room_id: int) -> GameRoom | None:
    stmt = (
        select(GameRoom)
        .where(GameRoom.id == room_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return await session.scalar(stmt)


async def list_participants(session: AsyncSession, room_id: int) -> list[GameParticipant]:
    """Return participants ordered by display_label so join order and bots never leak."""
    stmt = (
        select(GameParticipant)
        .where(GameParticipant.room_id == room_id)
        .order_by(GameParticipant.display_label.asc(), GameParticipant.id.asc())
    )
    return list(await session.scalars(stmt))


async def count_participants(session: AsyncSession, room_id: int) -> int:
    stmt = select(func.count(GameParticipant.id)).where(GameParticipant.room_id == room_id)
    return int(await session.scalar(stmt) or 0)


async def list_human_user_ids(session: AsyncSession, room_id: int) -> list[int]:
    stmt = select(GameParticipant.user_id).where(
        GameParticipant.room_id == room_id,
        GameParticipant.user_id.is_not(None),
    )
    return [uid for uid in await session.scalars(stmt) if uid is not None]


async def list_bot_participants(session: AsyncSession, room_id: int) -> list[GameParticipant]:
    stmt = (
        select(GameParticipant)
        .where(GameParticipant.room_id == room_id, GameParticipant.user_id.is_(None))
        .order_by(GameParticipant.id.asc())
    )
    return list(await session.scalars(stmt))


async def get_participant_for_user(
    session: AsyncSession, room_id: int, user_id: int
) -> GameParticipant | None:
    stmt = select(GameParticipant).where(
        GameParticipant.room_id == room_id, GameParticipant.user_id == user_id
    )
    return await session.scalar(stmt)


async def create_room(
    session: AsyncSession,
    *,
    target_size: int,
    room_expires_at: datetime,
    bot_plan: dict[str, Any] | None,
) -> GameRoom:
    room = GameRoom(
        target_size=target_size,
        state="waiting",
        room_expires_at=room_expires_at,
        bot_plan=bot_plan,
    )
    session.add(room)
    await session.flush()
    return room


async def add_participant(
    session: AsyncSession, *, room_id: int, user_id: int | None, display_label: str
) -> GameParticipant:
    participant = GameParticipant(
        room_id=room_id,
        user_id=user_id,
        display_label=display_label,
    )
    session.add(participant)
    await session.flush()
    return participant


async def delete_participant(session: AsyncSession, participant_id: int) -> None:
    await session.execute(delete(GameParticipant).where(GameParticipant.id == participant_id))


async def create_message(
    session: AsyncSession, *, room_id: int, participant_id: int, body: str, sent_at: datetime
) -> GameMessage:
    message = GameMessage(
        room_id=room_id,
        participant_id=participant_id,
        text=body,
        sent_at=sent_at,
    )
    session.add(message)
    await session.flush()
    return message


async def list_room_messages(
    session: AsyncSession, room_id: int, before_id: int | None, limit: int
) -> tuple[list[tuple[GameMessage, GameParticipant]], int | None]:
    """One page of a room's chat, each message with its author, oldest to newest.

    The page holds the `limit` newest messages with an id below `before_id` (all of them when
    it is None). The second value is the `before_id` of the next older page, or None when
    there is nothing older.
    """
    stmt = (
        select(GameMessage, GameParticipant)
        .join(GameParticipant, GameParticipant.id == GameMessage.participant_id)
        .where(GameMessage.room_id == room_id)
    )
    if before_id is not None:
        stmt = stmt.where(GameMessage.id < before_id)
    # One more than asked: if it exists, there is an older page.
    rows = (await session.execute(stmt.order_by(GameMessage.id.desc()).limit(limit + 1))).all()
    page = rows[:limit]
    prev_before_id = page[-1][0].id if len(rows) > limit else None
    return [(message, author) for message, author in reversed(page)], prev_before_id


async def list_active_room_ids(session: AsyncSession) -> list[int]:
    stmt = (
        select(GameRoom.id)
        .where(GameRoom.state.in_(("waiting", "discussion", "voting")))
        .order_by(GameRoom.id.asc())
    )
    return list(await session.scalars(stmt))
