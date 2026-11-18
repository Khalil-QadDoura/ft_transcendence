"""The /api/game routes for matchmaking, waiting room management, room state, votes and results."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.redis_client import get_redis
from app.db.session import get_session
from app.game import service
from app.game.constants import MAX_ID
from app.game.schemas import QueueJoinOut, RoomOut, RoomResultsOut, VoteIn, VoteOut

router = APIRouter(prefix="/game", tags=["game"])

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
