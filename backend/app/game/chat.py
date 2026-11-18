"""Room chat and resync (BE-09): the /ws/game socket, chat messages and their history, and the
snapshot a player gets each time the socket opens.

The socket listens on its user's Redis channel, like /ws (BE-06), so every game event the rest
of the game sends with send_to_user() reaches it as well. What /ws/game adds: the snapshot
first, then the `chat_message` frame.

Before the results, players know each other only by label number (1-5: "Player 3" is 3), never
by database id (rules, section 9). Every payload in this file follows that.
"""

import asyncio

from fastapi import HTTPException, WebSocket, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.metrics import track_ws_connection
from app.game import repo, service
from app.game.constants import MAX_ID, SNAPSHOT_MESSAGES, label_number
from app.game.models import GameMessage, GameParticipant, GameRoom
from app.game.schemas import (
    GameMessageEventOut,
    GameMessagesPage,
    GameSnapshotOut,
    MyVoteOut,
    RoomOut,
    RoomParticipantOut,
)
from app.realtime import repo as realtime_repo
from app.realtime import service as realtime_service
from app.realtime.schemas import Event
from app.users.models import User

NOT_A_PARTICIPANT = "Not a participant of this room"


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
    try:
        async with app.state.session_factory() as session:
            snapshot = await build_snapshot(session, app.state.settings, room_id, user.id)
        if snapshot is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=NOT_A_PARTICIPANT)
            return
        async with track_ws_connection(app):
            await send(websocket, "game_snapshot", snapshot)
            forwarding = asyncio.create_task(realtime_service.forward_events(pubsub, websocket))
            await read_room_frames(websocket, user, room_id)
    finally:
        if forwarding is not None:
            forwarding.cancel()
            await asyncio.wait({forwarding})  # until it has really stopped
        await pubsub.aclose()


async def read_room_frames(websocket: WebSocket, user: User, room_id: int) -> None:
    """Answer what the browser sends: `ping` gets `pong`. Anything else is ignored."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        frame = realtime_service.parse_frame(message.get("text"))
        if frame is None:
            continue
        if frame.get("type") == "ping":
            await send(websocket, "pong")
