"""Turing Duel matchmaking, hidden bot plans, room controls, and server-clock phase loop."""

import asyncio
import random
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.game import repo
from app.game.constants import (
    BOT_CHAT_TEMPLATES,
    MAX_PARTICIPANTS,
    MIN_EXPIRY_START_PARTICIPANTS,
    PLAYER_LABELS,
    START_NOW_MAX_PARTICIPANTS,
    START_NOW_MIN_PARTICIPANTS,
)
from app.game.models import GameParticipant, GameRoom
from app.game.schemas import (
    GameMessageEventOut,
    GameParticipantEventOut,
    GamePhaseEventOut,
    GameRoomEventOut,
    ParticipantOut,
    QueueJoinOut,
    RoomOut,
    RoomParticipantOut,
)
from app.realtime import service as realtime_service
from app.users.models import User

log = structlog.get_logger(__name__)

QueuedEvent = tuple[list[int], str, BaseModel]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _draw_label(participants: list[GameParticipant]) -> str:
    used = {p.display_label for p in participants}
    free = [label for label in PLAYER_LABELS if label not in used]
    if not free:
        raise RuntimeError("No free display labels remaining in room")
    return random.choice(free)


def _build_initial_bot_plan(now: datetime, settings: Settings) -> dict[str, Any]:
    """Secret server-only schedule for planned bots; never exposed before results."""
    if random.random() >= settings.game_bot_probability:
        return {"joins": [], "chats": []}
    bot_count = random.randint(1, MAX_PARTICIPANTS - 1)
    min_d = settings.game_bot_min_delay_sec
    max_d = max(min_d, settings.game_bot_max_delay_sec)
    join_times = sorted(now.timestamp() + random.uniform(min_d, max_d) for _ in range(bot_count))
    return {"joins": join_times, "chats": []}


def _schedule_bot_chats(
    bots: list[GameParticipant], now: datetime, settings: Settings
) -> list[dict[str, Any]]:
    """Plan template discussion messages with natural typing delays for joined bots."""
    if not bots:
        return []
    discussion_end_ts = now.timestamp() + settings.game_discussion_sec
    min_d = settings.game_bot_chat_min_delay_sec
    max_d = max(min_d, settings.game_bot_chat_max_delay_sec)
    if settings.game_discussion_sec <= min_d:
        return []
    capped_max = min(max_d, settings.game_discussion_sec * 0.85)
    chats: list[dict[str, Any]] = []
    for bot in bots:
        lines = random.sample(BOT_CHAT_TEMPLATES, k=min(2, len(BOT_CHAT_TEMPLATES)))
        send_ts = now.timestamp() + random.uniform(min_d, max(min_d, capped_max))
        for idx, line in enumerate(lines):
            msg_ts = send_ts + idx * random.uniform(min_d * 0.5, max(min_d, capped_max * 0.6))
            if msg_ts < discussion_end_ts - 0.05:
                chats.append({"participant_id": bot.id, "send_at": msg_ts, "text": line})
    chats.sort(key=lambda item: item["send_at"])
    return chats


def _phase_ends_at(room: GameRoom, settings: Settings) -> datetime | None:
    if room.state == "waiting":
        return room.room_expires_at
    if room.state == "discussion" and room.discussion_started_at is not None:
        return room.discussion_started_at + timedelta(seconds=settings.game_discussion_sec)
    if room.state == "voting" and room.voting_started_at is not None:
        return room.voting_started_at + timedelta(seconds=settings.game_voting_sec)
    return None


def _serialize_room(
    room: GameRoom,
    participants: list[GameParticipant],
    me: GameParticipant,
    settings: Settings,
) -> RoomOut:
    """Build RoomOut identically across all other humans and bots."""
    return RoomOut(
        id=room.id,
        state=room.state,
        target_size=room.target_size,
        participant_count=len(participants),
        my_participant_id=me.id,
        room_expires_at=room.room_expires_at,
        phase_ends_at=_phase_ends_at(room, settings),
        participants=[
            RoomParticipantOut(
                id=p.id,
                display_label=p.display_label,
                is_you=(p.id == me.id),
            )
            for p in participants
        ],
    )


async def _push_events(redis: Redis, events: list[QueuedEvent]) -> None:
    """Broadcast committed WebSocket events through BE-06 per-user pub/sub."""
    for user_ids, event_type, payload in events:
        for uid in user_ids:
            await realtime_service.send_to_user(redis, uid, event_type, payload)


async def _start_discussion(
    session: AsyncSession,
    room: GameRoom,
    now: datetime,
    settings: Settings,
    human_ids: list[int],
) -> QueuedEvent:
    """Move a waiting room into discussion and drop any unjoined planned bots."""
    bots = await repo.list_bot_participants(session, room.id)
    room.state = "discussion"
    room.discussion_started_at = now
    room.bot_plan = {"joins": [], "chats": _schedule_bot_chats(bots, now, settings)}
    phase_end = now + timedelta(seconds=settings.game_discussion_sec)
    return (
        human_ids,
        "game_started",
        GamePhaseEventOut(room_id=room.id, state="discussion", phase_ends_at=phase_end),
    )


async def join_queue(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    user: User,
) -> QueueJoinOut:
    """Place the user into the oldest open waiting room (<5 seats) or create a new one."""
    events: list[QueuedEvent] = []
    async with repo.matchmaking_lock(redis):
        existing = await repo.get_user_active_membership(session, user.id)
        if existing is not None:
            room, _ = existing
            if room.state == "waiting":
                return QueueJoinOut(message="queued", room_id=room.id)
            raise HTTPException(status_code=409, detail="Already in an active game room")

        now = _utcnow()
        candidate = await repo.find_oldest_open_waiting_room(session, now)
        room_id: int | None = candidate.id if candidate is not None else None
        if room_id is not None:
            # Wait if the room was mid-tick/start; if it closed or filled, open a fresh room.
            if not await _join_locked_room(session, redis, settings, room_id, user.id, now, events):
                room_id = None
        if room_id is None:
            now = _utcnow()
            fresh = await repo.create_room(
                session,
                target_size=MAX_PARTICIPANTS,
                room_expires_at=now + timedelta(seconds=settings.game_wait_timeout_sec),
                bot_plan=_build_initial_bot_plan(now, settings),
            )
            room_id = fresh.id
            if not await _join_locked_room(session, redis, settings, room_id, user.id, now, events):
                raise HTTPException(status_code=409, detail="Could not join new room")

    await _push_events(redis, events)
    return QueueJoinOut(message="queued", room_id=room_id)


async def _join_locked_room(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    room_id: int,
    user_id: int,
    now: datetime,
    events: list[QueuedEvent],
) -> bool:
    async with repo.room_lock(redis, room_id):
        room = await repo.get_room_for_update(session, room_id)
        if room is None or room.state != "waiting":
            return False
        if room.room_expires_at is not None and room.room_expires_at <= now:
            return False
        participants = await repo.list_participants(session, room.id)
        if len(participants) >= MAX_PARTICIPANTS:
            return False

        label = _draw_label(participants)
        participant = await repo.add_participant(
            session, room_id=room.id, user_id=user_id, display_label=label
        )
        new_count = len(participants) + 1
        human_ids = [p.user_id for p in participants if p.user_id is not None] + [user_id]
        events.append(([user_id], "game_room_formed", GameRoomEventOut(room_id=room.id)))
        events.append(
            (
                human_ids,
                "game_participant_joined",
                GameParticipantEventOut(
                    room_id=room.id,
                    participant=ParticipantOut.model_validate(participant),
                    participant_count=new_count,
                    room_expires_at=room.room_expires_at,
                ),
            )
        )
        if new_count >= MAX_PARTICIPANTS:
            events.append(await _start_discussion(session, room, now, settings, human_ids))
        await session.commit()
        return True


async def leave_queue(session: AsyncSession, redis: Redis, user: User) -> None:
    """Remove the user from a waiting room, freeing their label; close if last human leaves."""
    membership = await repo.get_user_active_membership(session, user.id)
    if membership is None or membership[0].state != "waiting":
        return
    room_id = membership[0].id
    events: list[QueuedEvent] = []

    async with repo.room_lock(redis, room_id):
        room = await repo.get_room_for_update(session, room_id)
        if room is None or room.state != "waiting":
            return
        me = await repo.get_participant_for_user(session, room_id, user.id)
        if me is None:
            return
        participants = await repo.list_participants(session, room_id)
        remaining_humans = [
            p.user_id for p in participants if p.user_id is not None and p.user_id != user.id
        ]
        await repo.delete_participant(session, me.id)
        if not remaining_humans:
            room.state = "closed"
            room.bot_plan = None
        else:
            events.append(
                (
                    remaining_humans,
                    "game_participant_left",
                    GameParticipantEventOut(
                        room_id=room.id,
                        participant=ParticipantOut.model_validate(me),
                        participant_count=len(participants) - 1,
                        room_expires_at=room.room_expires_at,
                    ),
                )
            )
        await session.commit()

    await _push_events(redis, events)


async def get_room(session: AsyncSession, settings: Settings, user: User, room_id: int) -> RoomOut:
    """Return room details for one of its participants without exposing any bot flags."""
    room = await repo.get_room(session, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    me = await repo.get_participant_for_user(session, room_id, user.id)
    if me is None:
        raise HTTPException(status_code=403, detail="Not a participant of this room")
    participants = await repo.list_participants(session, room_id)
    return _serialize_room(room, participants, me, settings)


async def start_room(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    user: User,
    room_id: int,
) -> RoomOut:
    """Start a waiting room with 2–4 participants under a Redis lock; idempotent on repeat."""
    events: list[QueuedEvent] = []
    async with repo.room_lock(redis, room_id):
        room = await repo.get_room_for_update(session, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")
        me = await repo.get_participant_for_user(session, room_id, user.id)
        if me is None:
            raise HTTPException(status_code=403, detail="Not a participant of this room")
        participants = await repo.list_participants(session, room_id)
        if room.state == "discussion":
            return _serialize_room(room, participants, me, settings)
        if room.state != "waiting":
            raise HTTPException(
                status_code=409, detail=f"Cannot start room in state '{room.state}'"
            )
        count = len(participants)
        if count < START_NOW_MIN_PARTICIPANTS or count > START_NOW_MAX_PARTICIPANTS:
            raise HTTPException(status_code=409, detail="Start now requires 2 to 4 participants")

        now = _utcnow()
        human_ids = [p.user_id for p in participants if p.user_id is not None]
        events.append(await _start_discussion(session, room, now, settings, human_ids))
        await session.commit()
        result = _serialize_room(room, participants, me, settings)

    await _push_events(redis, events)
    return result


async def process_room_tick(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    room_id: int,
) -> None:
    """Advance scheduled bot joins, room wait expiry, bot discussion chat, and server phases."""
    events: list[QueuedEvent] = []
    try:
        lock_ctx = repo.room_lock(redis, room_id, blocking_timeout=0.1)
        async with lock_ctx:
            async with session_factory() as session:
                room = await repo.get_room_for_update(session, room_id)
                if room is None:
                    return
                now = _utcnow()
                if room.state == "waiting":
                    await _tick_waiting_room(session, room, now, settings, events)
                elif room.state == "discussion":
                    await _tick_discussion_room(session, room, now, settings, events)
                elif room.state == "voting":
                    await _tick_voting_room(session, room, now, settings, events)
    except TimeoutError:
        return
    await _push_events(redis, events)


async def _tick_waiting_room(
    session: AsyncSession,
    room: GameRoom,
    now: datetime,
    settings: Settings,
    events: list[QueuedEvent],
) -> None:
    participants = await repo.list_participants(session, room.id)
    human_ids = [p.user_id for p in participants if p.user_id is not None]
    if not human_ids:
        room.state = "closed"
        room.bot_plan = None
        await session.commit()
        return

    if room.room_expires_at is not None and now >= room.room_expires_at:
        if len(participants) >= MIN_EXPIRY_START_PARTICIPANTS:
            events.append(await _start_discussion(session, room, now, settings, human_ids))
        else:
            room.state = "closed"
            room.bot_plan = None
            events.append((human_ids, "game_room_closed", GameRoomEventOut(room_id=room.id)))
        await session.commit()
        return

    plan = dict(room.bot_plan or {})
    joins = list(plan.get("joins") or [])
    if not joins or joins[0] > now.timestamp():
        return

    joins.pop(0)
    if len(participants) < MAX_PARTICIPANTS:
        label = _draw_label(participants)
        bot = await repo.add_participant(
            session, room_id=room.id, user_id=None, display_label=label
        )
        new_count = len(participants) + 1
        events.append(
            (
                human_ids,
                "game_participant_joined",
                GameParticipantEventOut(
                    room_id=room.id,
                    participant=ParticipantOut.model_validate(bot),
                    participant_count=new_count,
                    room_expires_at=room.room_expires_at,
                ),
            )
        )
        if new_count >= MAX_PARTICIPANTS:
            events.append(await _start_discussion(session, room, now, settings, human_ids))
        else:
            room.bot_plan = {**plan, "joins": joins}
    else:
        room.bot_plan = {**plan, "joins": []}
    await session.commit()


async def _tick_discussion_room(
    session: AsyncSession,
    room: GameRoom,
    now: datetime,
    settings: Settings,
    events: list[QueuedEvent],
) -> None:
    human_ids = await repo.list_human_user_ids(session, room.id)
    discussion_start = room.discussion_started_at or room.created_at
    discussion_end = discussion_start + timedelta(seconds=settings.game_discussion_sec)
    if now >= discussion_end:
        room.state = "voting"
        room.voting_started_at = now
        room.bot_plan = None
        voting_end = now + timedelta(seconds=settings.game_voting_sec)
        events.append(
            (
                human_ids,
                "game_phase_voting",
                GamePhaseEventOut(room_id=room.id, state="voting", phase_ends_at=voting_end),
            )
        )
        await session.commit()
        return

    plan = dict(room.bot_plan or {})
    chats = list(plan.get("chats") or [])
    if not chats or chats[0]["send_at"] > now.timestamp():
        return

    item = chats.pop(0)
    bots = {b.id: b for b in await repo.list_bot_participants(session, room.id)}
    bot = bots.get(item["participant_id"])
    room.bot_plan = {**plan, "chats": chats}
    if bot is not None:
        message = await repo.create_message(
            session,
            room_id=room.id,
            participant_id=bot.id,
            body=item["text"],
            sent_at=now,
        )
        events.append(
            (
                human_ids,
                "game_message",
                GameMessageEventOut(
                    id=message.id,
                    participant_id=bot.id,
                    display_label=bot.display_label,
                    text=message.text,
                ),
            )
        )
    await session.commit()


async def _tick_voting_room(
    session: AsyncSession,
    room: GameRoom,
    now: datetime,
    settings: Settings,
    events: list[QueuedEvent],
) -> None:
    voting_start = room.voting_started_at or now
    if now < voting_start + timedelta(seconds=settings.game_voting_sec):
        return
    human_ids = await repo.list_human_user_ids(session, room.id)
    room.state = "finished"
    room.finished_at = now
    await session.commit()
    events.append((human_ids, "game_phase_finished", GameRoomEventOut(room_id=room.id)))


async def tick_all_active_rooms(app: FastAPI) -> None:
    """Process one tick across all active rooms; safe across multiple API workers."""
    async with app.state.session_factory() as session:
        room_ids = await repo.list_active_room_ids(session)
    for room_id in room_ids:
        await process_room_tick(
            app.state.session_factory,
            app.state.redis,
            app.state.settings,
            room_id,
        )


async def run_scheduler(app: FastAPI) -> None:
    """Background server-clock loop started in app lifespan; survives transient errors."""
    interval = app.state.settings.game_tick_interval_sec
    while True:
        try:
            await tick_all_active_rooms(app)
        except asyncio.CancelledError:
            raise
        except (RedisError, SQLAlchemyError, OSError):
            log.warning("game scheduler tick skipped", exc_info=True)
        except Exception:
            log.exception("game scheduler tick failed")
        # A cancel request can be used up inside a library without a CancelledError reaching
        # here (seen in redis-py while it opens a new connection). Stop on the request itself,
        # or the loop goes on and the lifespan shutdown waits for this task forever.
        if asyncio.current_task().cancelling():
            return
        with suppress(asyncio.CancelledError):
            await asyncio.sleep(interval)
            continue
        break
