"""HTTP endpoints for friendships and public user profiles (BE-22)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.redis_client import get_redis
from app.core.storage import Storage, get_storage
from app.db.session import get_session
from app.friends import service
from app.friends.schemas import (
    FriendOut,
    FriendRequestCreate,
    FriendshipOut,
    PublicProfileOut,
)
from app.media.constants import MAX_ID

router = APIRouter(prefix="/friends", tags=["friends"])
users_router = APIRouter(prefix="/users", tags=["friends"])

Session = Annotated[AsyncSession, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]
Files = Annotated[Storage, Depends(get_storage)]
DbId = Annotated[int, Path(ge=1, le=MAX_ID)]


@router.post("/requests", response_model=FriendshipOut, status_code=status.HTTP_201_CREATED)
async def send_friend_request(
    payload: FriendRequestCreate,
    user: CurrentUser,
    session: Session,
) -> FriendshipOut:
    """Send a friend request to another active user."""
    row = await service.send_request(
        session, requester_id=user.id, addressee_id=payload.addressee_id
    )
    return FriendshipOut.model_validate(row)


@router.get("/requests", response_model=list[FriendshipOut])
async def list_incoming_requests(user: CurrentUser, session: Session) -> list[FriendshipOut]:
    """List pending incoming friend requests for the authenticated user."""
    rows = await service.list_incoming_requests(session, user_id=user.id)
    return [FriendshipOut.model_validate(r) for r in rows]


@router.post("/requests/{friendship_id}/accept", response_model=FriendshipOut)
async def accept_friend_request(
    friendship_id: DbId,
    user: CurrentUser,
    session: Session,
) -> FriendshipOut:
    """Accept an incoming pending friend request."""
    row = await service.accept_request(session, friendship_id=friendship_id, user_id=user.id)
    return FriendshipOut.model_validate(row)


@router.post("/requests/{friendship_id}/decline", response_model=FriendshipOut)
async def decline_friend_request(
    friendship_id: DbId,
    user: CurrentUser,
    session: Session,
) -> FriendshipOut:
    """Decline an incoming pending friend request."""
    row = await service.decline_request(session, friendship_id=friendship_id, user_id=user.id)
    return FriendshipOut.model_validate(row)


@router.delete("/{friendship_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_friend(friendship_id: DbId, user: CurrentUser, session: Session) -> None:
    """Remove an accepted friend or cancel a pending friend request."""
    await service.remove_friend(session, friendship_id=friendship_id, user_id=user.id)


@router.get("", response_model=list[FriendOut])
async def list_my_friends(
    user: CurrentUser,
    session: Session,
    redis: RedisClient,
    storage: Files,
) -> list[FriendOut]:
    """Return accepted active friends in a single query with avatar_url and online status."""
    return await service.list_friends(session, redis, storage, user_id=user.id)


@users_router.get("/{user_id}/profile", response_model=PublicProfileOut)
async def get_public_profile(
    user_id: DbId,
    user: CurrentUser,
    session: Session,
    redis: RedisClient,
    storage: Files,
) -> PublicProfileOut:
    """Return an active user's public profile, avatar_url, online status, and relation."""
    return await service.get_public_profile(
        session, redis, storage, viewer_id=user.id, target_user_id=user_id
    )
