"""Room chat and resync (BE-09): the /ws/game socket, chat messages and their history, and the
snapshot a player gets each time the socket opens.

The socket listens on its user's Redis channel, like /ws (BE-06), so every game event the rest
of the game sends with send_to_user() reaches it as well. What /ws/game adds: the snapshot
first, then the `chat_message` frame.

Before the results, players know each other only by label number (1-5: "Player 3" is 3), never
by database id (rules, section 9). Every payload in this file follows that.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.metrics import track_ws_connection
from app.game import repo, service
from app.game.constants import (
    DISCONNECT_GRACE_SEC,
    MAX_ID,
    MESSAGE_MAX_LENGTH,
    SNAPSHOT_MESSAGES,
    disconnect_at_key,
    disconnect_expired_key,
    disconnect_grace_key,
    label_number,
    room_presence_key,
)
from app.game.models import GameMessage, GameParticipant, GameRoom
from app.game.schemas import (
    GameErrorOut,
    GameMessageEventOut,
    GameMessagesPage,
    GameSnapshotOut,
    MyVoteOut,
    PlayerConnectionEventOut,
    RoomOut,
    RoomParticipantOut,
)
from app.realtime import repo as realtime_repo
from app.realtime import service as realtime_service
from app.realtime.schemas import Event
from app.users.models import User

NOT_A_PARTICIPANT = "Not a participant of this room"
CHAT_CLOSED = "Chat is open only during the discussion"


def message_out(message: GameMessage, author: GameParticipant) -> GameMessageEventOut:
    """A chat message as players see it: the author by label number, never by database id."""
    return GameMessageEventOut(
        id=message.id,
        participant_id=label_number(author.display_label),
        display_label=author.display_label,
        text=message.text,
    )


def room_out(
    room: GameRoom, participants: list[GameParticipant], me: GameParticipant, settings: Settings
) -> RoomOut:
    """The room in the shape of GET /api/game/rooms/{id}, with label numbers as ids."""
    return RoomOut(
        id=room.id,
        state=room.state,
        target_size=room.target_size,
        participant_count=len(participants),
        my_participant_id=label_number(me.display_label),
        room_expires_at=room.room_expires_at,
        phase_ends_at=service._phase_ends_at(room, settings),
        participants=[
            RoomParticipantOut(
                id=label_number(p.display_label),
                display_label=p.display_label,
                is_you=(p.id == me.id),
            )
            for p in participants
        ],
    )


async def list_messages(
    session: AsyncSession, user: User, room_id: int, before_id: int | None, limit: int
) -> GameMessagesPage:
    """GET /api/game/rooms/{id}/messages: one page of the room's chat, for its participants."""
    if await repo.get_room(session, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if await repo.get_participant_for_user(session, room_id, user.id) is None:
        raise HTTPException(status_code=403, detail=NOT_A_PARTICIPANT)
    rows, prev_before_id = await repo.list_room_messages(session, room_id, before_id, limit)
    return GameMessagesPage(
        items=[message_out(message, author) for message, author in rows],
        prev_before_id=prev_before_id,
    )


async def build_snapshot(
    session: AsyncSession, settings: Settings, room_id: int, user_id: int
) -> GameSnapshotOut | None:
    """The room as this participant sees it right now: its state, everyone in it, when the
    phase ends, the recent chat and my own marks. None when the user is not in the room."""
    room = await repo.get_room(session, room_id)
    me = await repo.get_participant_for_user(session, room_id, user_id)
    if room is None or me is None:
        return None
    participants = await repo.list_participants(session, room_id)
    messages, _ = await repo.list_room_messages(session, room_id, None, SNAPSHOT_MESSAGES)
    labels = {p.id: p.display_label for p in participants}
    return GameSnapshotOut(
        room=room_out(room, participants, me, settings),
        messages=[message_out(message, author) for message, author in messages],
        my_votes=[
            MyVoteOut(
                target_participant_id=label_number(labels[vote.target_participant_id]),
                guess=vote.guess,
            )
            for vote in await repo.list_votes_of(session, me.id)
            # A mark on someone outside this room is never shown (BE-10 refuses to save one).
            if vote.target_participant_id in labels
        ],
    )


def parse_room_id(raw: str) -> int | None:
    """The room id from the socket's address (?room_id=7), or None if it is not 1 to MAX_ID."""
    if not (raw.isascii() and raw.isdigit()):
        return None
    room_id = int(raw)
    return room_id if 1 <= room_id <= MAX_ID else None


async def send(websocket: WebSocket, event_type: str, payload: BaseModel | None = None) -> None:
    """Send one {type, payload} frame to this socket only."""
    await websocket.send_text(Event(type=event_type, payload=payload).model_dump_json())


async def add_room_socket(
    redis: Redis, room_id: int, user_id: int, socket_id: str, ttl_seconds: int = 3600
) -> int:
    """Track this socket in the user's room presence key. Returns the number of open sockets for
    this user in this room (1 means this is the first).
    """
    key = room_presence_key(room_id, user_id)
    now = time.time()
    async with redis.pipeline(transaction=True) as steps:
        steps.zremrangebyscore(key, "-inf", now)
        steps.zadd(key, {socket_id: now + ttl_seconds})
        steps.expire(key, ttl_seconds)
        steps.zcard(key)
        *_, live = await steps.execute()
    return live


async def refresh_room_socket(
    redis: Redis, room_id: int, user_id: int, socket_id: str, ttl_seconds: int = 3600
) -> None:
    """Keep this room socket alive on ping."""
    key = room_presence_key(room_id, user_id)
    async with redis.pipeline(transaction=True) as steps:
        steps.zadd(key, {socket_id: time.time() + ttl_seconds})
        steps.expire(key, ttl_seconds)
        await steps.execute()


async def remove_room_socket(redis: Redis, room_id: int, user_id: int, socket_id: str) -> int:
    """Remove this socket from the user's room presence key. Returns how many open sockets remain
    (0 means this was the last socket).
    """
    key = room_presence_key(room_id, user_id)
    async with redis.pipeline(transaction=True) as steps:
        steps.zrem(key, socket_id)
        steps.zremrangebyscore(key, "-inf", time.time())
        steps.zcard(key)
        *_, live = await steps.execute()
    return live


async def is_disconnect_expired(
    redis: Redis, room_id: int, participant_id: int, label_num: int
) -> bool:
    """True if this participant disconnected and their 30 s grace period has expired."""
    if await redis.exists(disconnect_expired_key(room_id, participant_id)) or await redis.exists(
        disconnect_expired_key(room_id, label_num)
    ):
        return True
    if await redis.exists(disconnect_at_key(room_id, participant_id)) or await redis.exists(
        disconnect_at_key(room_id, label_num)
    ):
        if not (
            await redis.exists(disconnect_grace_key(room_id, participant_id))
            or await redis.exists(disconnect_grace_key(room_id, label_num))
        ):
            return True
    return False


async def on_participant_connected(
    redis: Redis, room_id: int, me: GameParticipant, peers: list[int], user_id: int
) -> None:
    """Called when a user opens their first /ws/game socket in this room."""
    lbl_num = label_number(me.display_label)
    is_already_expired = bool(
        await redis.exists(disconnect_expired_key(room_id, me.id))
        or await redis.exists(disconnect_expired_key(room_id, lbl_num))
    )
    had_grace = bool(
        await redis.exists(disconnect_grace_key(room_id, me.id))
        or await redis.exists(disconnect_grace_key(room_id, lbl_num))
    )
    had_disconnect_at = bool(
        await redis.exists(disconnect_at_key(room_id, me.id))
        or await redis.exists(disconnect_at_key(room_id, lbl_num))
    )

    if is_already_expired:
        pass
    elif had_grace:
        await redis.delete(
            disconnect_grace_key(room_id, me.id),
            disconnect_grace_key(room_id, lbl_num),
            disconnect_at_key(room_id, me.id),
            disconnect_at_key(room_id, lbl_num),
        )
    elif had_disconnect_at:
        await redis.set(disconnect_expired_key(room_id, me.id), "1", ex=3600)
        await redis.set(disconnect_expired_key(room_id, lbl_num), "1", ex=3600)
        await redis.delete(
            disconnect_at_key(room_id, me.id),
            disconnect_at_key(room_id, lbl_num),
        )

    event = PlayerConnectionEventOut(participant_id=lbl_num, connected=True)
    for peer_id in peers:
        if peer_id != user_id:
            await realtime_service.send_to_user(redis, peer_id, "player_connection", event)


async def on_participant_disconnected(
    redis: Redis, room_id: int, me: GameParticipant, peers: list[int], user_id: int
) -> None:
    """Called when a user closes their last /ws/game socket in this room during an active game."""
    lbl_num = label_number(me.display_label)
    now_ts = str(time.time())
    is_already_expired = bool(
        await redis.exists(disconnect_expired_key(room_id, me.id))
        or await redis.exists(disconnect_expired_key(room_id, lbl_num))
    )
    if not is_already_expired:
        await redis.set(disconnect_grace_key(room_id, me.id), "1", ex=DISCONNECT_GRACE_SEC)
        await redis.set(disconnect_grace_key(room_id, lbl_num), "1", ex=DISCONNECT_GRACE_SEC)
        await redis.set(disconnect_at_key(room_id, me.id), now_ts, ex=3600)
        await redis.set(disconnect_at_key(room_id, lbl_num), now_ts, ex=3600)

    event = PlayerConnectionEventOut(participant_id=lbl_num, connected=False)
    for peer_id in peers:
        if peer_id != user_id:
            await realtime_service.send_to_user(redis, peer_id, "player_connection", event)


async def serve_room_socket(websocket: WebSocket, user: User) -> None:
    """The life of one /ws/game socket, after the ticket check, until the client goes away.

    A user who is not a participant of the room (or names no valid room) is closed with 1008,
    as a bad ticket is. A participant gets the snapshot first, then the live events.
    """
    app = websocket.app
    room_id = parse_room_id(websocket.query_params.get("room_id", ""))
    if room_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=NOT_A_PARTICIPANT)
        return
    pubsub = app.state.redis.pubsub()
    # Listen first, read the snapshot second: an event sent in between waits in Redis until
    # the forwarding starts, so nothing falls between the snapshot and the live events. Such
    # an event may repeat something the snapshot already has; the client keeps one (same id).
    await pubsub.subscribe(realtime_repo.user_channel(user.id))
    forwarding = None
    socket_id = uuid.uuid4().hex
    try:
        async with app.state.session_factory() as session:
            snapshot = await build_snapshot(session, app.state.settings, room_id, user.id)
            if snapshot is None:
                await websocket.close(
                    code=status.WS_1008_POLICY_VIOLATION, reason=NOT_A_PARTICIPANT
                )
                return
            room = await repo.get_room(session, room_id)
            me = await repo.get_participant_for_user(session, room_id, user.id)
            peers = await repo.list_human_user_ids(session, room_id)

        async with track_ws_connection(app):
            live = await add_room_socket(app.state.redis, room_id, user.id, socket_id)
            if (
                live == 1
                and room is not None
                and me is not None
                and room.state not in ("finished", "closed")
            ):
                await on_participant_connected(app.state.redis, room_id, me, peers, user.id)

            await send(websocket, "game_snapshot", snapshot)
            forwarding = asyncio.create_task(realtime_service.forward_events(pubsub, websocket))
            await read_room_frames(websocket, user, room_id, socket_id)
    finally:
        if forwarding is not None:
            forwarding.cancel()
            await asyncio.wait({forwarding})  # until it has really stopped
        await pubsub.aclose()
        live = await remove_room_socket(app.state.redis, room_id, user.id, socket_id)
        if live == 0:
            async with app.state.session_factory() as session:
                room = await repo.get_room(session, room_id)
                me = await repo.get_participant_for_user(session, room_id, user.id)
                peers = await repo.list_human_user_ids(session, room_id)
            if room is not None and me is not None and room.state not in ("finished", "closed"):
                await on_participant_disconnected(app.state.redis, room_id, me, peers, user.id)


async def read_room_frames(websocket: WebSocket, user: User, room_id: int, socket_id: str) -> None:
    """Answer what the browser sends: `ping` gets `pong`; `chat_message` goes to the room, or
    gets a `game_error` that says why not. Anything else is ignored."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        frame = realtime_service.parse_frame(message.get("text"))
        if frame is None:
            continue
        kind = frame.get("type")
        if kind == "ping":
            await refresh_room_socket(websocket.app.state.redis, room_id, user.id, socket_id)
            await send(websocket, "pong")
        elif kind == "chat_message":
            refusal = await post_message(websocket.app, user, room_id, chat_text(frame))
            if refusal is not None:
                await send(websocket, "game_error", GameErrorOut(detail=refusal))


def chat_text(frame: dict[str, Any]) -> Any:
    """The text of a chat_message frame: at the top level ({"type", "text"}, as the frontend
    client sends it) or inside "payload", like the receipt frames of /ws."""
    payload = frame.get("payload")
    if isinstance(payload, dict) and "text" in payload:
        return payload["text"]
    return frame.get("text")


def text_refusal(text: Any) -> str | None:
    """Why this chat text cannot be saved, or None when it can."""
    if not isinstance(text, str) or not text.strip():
        return "Message is empty"
    if len(text.strip()) > MESSAGE_MAX_LENGTH:
        return f"Message is longer than {MESSAGE_MAX_LENGTH} characters"
    # PostgreSQL text cannot hold a NUL character, and UTF-8 cannot hold a lone surrogate
    # (JSON can carry both, as "\u0000" and "\ud800"). Refused here, not a database error.
    if "\x00" in text:
        return "Message has characters that cannot be saved"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "Message has characters that cannot be saved"
    return None


async def post_message(app: FastAPI, user: User, room_id: int, text: Any) -> str | None:
    """Save a chat message and send it as `game_message` to every human of the room, the
    author too (so all of the author's tabs show it). Returns why it was refused, or None.

    Bots post their lines from the game's server loop (service._tick_discussion_room) in the
    same table and with the same event, so players cannot tell them apart.
    """
    refusal = text_refusal(text)
    if refusal is not None:
        return refusal
    async with app.state.session_factory() as session:
        # A shared lock on the room until the commit: the phase cannot change while the
        # message is saved. Only this lock is taken (no Redis lock), so it cannot deadlock
        # with the server loop, which takes the Redis lock and then the row.
        room = await repo.get_room_for_share(session, room_id)
        author = await repo.get_participant_for_user(session, room_id, user.id)
        if room is None or author is None:
            return NOT_A_PARTICIPANT
        if await is_disconnect_expired(
            app.state.redis, room_id, author.id, label_number(author.display_label)
        ):
            return "Grace period expired"
        now = datetime.now(UTC)
        ends_at = service._phase_ends_at(room, app.state.settings)
        # The server loop moves the room to voting a moment after the 120 s; the clock decides.
        if room.state != "discussion" or (ends_at is not None and now >= ends_at):
            return CHAT_CLOSED
        message = await repo.create_message(
            session, room_id=room_id, participant_id=author.id, body=text.strip(), sent_at=now
        )
        human_ids = await repo.list_human_user_ids(session, room_id)
        event = message_out(message, author)
        await session.commit()
    for user_id in human_ids:
        await realtime_service.send_to_user(app.state.redis, user_id, "game_message", event)
    return None
