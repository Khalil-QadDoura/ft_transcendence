"""The /api/game routes for matchmaking, waiting room management, room state, votes and results,
and the room socket at /ws/game (BE-09)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, WebSocket
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.redis_client import get_redis
from app.db.session import get_session
from app.game import chat, service
from app.game.constants import HISTORY_PAGE_DEFAULT, HISTORY_PAGE_MAX, MAX_ID
from app.game.schemas import (
    GameMessagesPage,
    QueueJoinOut,
    RoomOut,
    RoomResultsOut,
    VoteIn,
    VoteOut,
)
from app.realtime import service as realtime_service

router = APIRouter(prefix="/game", tags=["game"])
socket_router = APIRouter()  # mounted at the root, like /ws: the proxy passes /ws/game as it is

Session = Annotated[AsyncSession, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]
RoomIdPath = Annotated[int, Path(ge=1, le=MAX_ID)]


@router.post("/queue/join", status_code=202)
async def join_queue(
    request: Request,
    user: CurrentUser,
    session: Session,
    redis: RedisClient,
) -> QueueJoinOut:
    """Assign the caller to the oldest open waiting room (<5 seats) or create a new room."""
    return await service.join_queue(session, redis, request.app.state.settings, user)


@router.delete("/queue/leave", status_code=204)
async def leave_queue(
    user: CurrentUser,
    session: Session,
    redis: RedisClient,
) -> Response:
    """Leave a waiting room cleanly; closes the room if the last human leaves."""
    await service.leave_queue(session, redis, user)
    return Response(status_code=204)


@router.get("/rooms/{room_id}")
async def get_room(
    room_id: RoomIdPath,
    request: Request,
    user: CurrentUser,
    session: Session,
) -> RoomOut:
    """Return room details for a participant without revealing bot identity or plans."""
    return await service.get_room(session, request.app.state.settings, user, room_id)


@router.get("/rooms/{room_id}/messages")
async def list_room_messages(
    room_id: RoomIdPath,
    user: CurrentUser,
    session: Session,
    before_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=HISTORY_PAGE_MAX)] = HISTORY_PAGE_DEFAULT,
) -> GameMessagesPage:
    """The room's chat, oldest to newest, a page at a time; for its participants only."""
    return await chat.list_messages(session, user, room_id, before_id, limit)


@socket_router.websocket("/ws/game")
async def room_socket(websocket: WebSocket) -> None:
    """The room's live connection: wss://<host>/ws/game?ticket=<ticket>&room_id=<id>.

    Same one-time ticket and same check as /ws. It sends a `game_snapshot` first, then every
    event of the user; it takes `chat_message` frames during the discussion."""
    user = await realtime_service.authenticate_ws(websocket)
    if user is None:
        return  # already closed with code 1008
    await chat.serve_room_socket(websocket, user)


@router.post("/rooms/{room_id}/start")
async def start_room(
    room_id: RoomIdPath,
    request: Request,
    user: CurrentUser,
    session: Session,
    redis: RedisClient,
) -> RoomOut:
    """Start a waiting room early with 2–4 participants; idempotent across concurrent presses."""
    return await service.start_room(session, redis, request.app.state.settings, user, room_id)


@router.post("/rooms/{room_id}/votes")
async def cast_vote(
    room_id: RoomIdPath,
    vote: VoteIn,
    request: Request,
    user: CurrentUser,
    session: Session,
) -> VoteOut:
    """Mark another participant (by label number) as bot or human; a new mark replaces the old."""
    return await service.cast_vote(session, request.app.state.settings, user, room_id, vote)


@router.get("/rooms/{room_id}/results")
async def get_results(
    room_id: RoomIdPath,
    user: CurrentUser,
    session: Session,
) -> RoomResultsOut:
    """Bots revealed, scores, outcomes and deception rates, once the room is finished."""
    return await service.get_results(session, user, room_id)
