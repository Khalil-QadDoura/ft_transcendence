"""Business rules for friend requests, friends list, and public user profiles."""

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import Storage
from app.friends import repo
from app.friends.models import Friendship
from app.friends.schemas import FriendOut, FriendshipStatusView, PublicProfileOut
from app.realtime import service as realtime_service


async def send_request(
    session: AsyncSession, *, requester_id: int, addressee_id: int
) -> Friendship:
    """Send a pending friend request to another active user."""
    if requester_id == addressee_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send a friend request to yourself",
        )

    target = await repo.get_active_user(session, addressee_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = await repo.get_live_friendship_for_pair(session, requester_id, addressee_id)
    if existing is not None:
        detail = (
            "Already friends" if existing.status == "accepted" else "Friend request already pending"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    try:
        return await repo.create_friend_request(session, requester_id, addressee_id)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Friend request already pending",
        ) from None


async def list_incoming_requests(session: AsyncSession, *, user_id: int) -> list[Friendship]:
    """List pending incoming friend requests for the caller."""
    return await repo.list_incoming_requests(session, user_id)


async def _respond_to_request(
    session: AsyncSession,
    *,
    friendship_id: int,
    user_id: int,
    new_status: str,
) -> Friendship:
    """Transition a pending request as addressee under a row lock."""
    row = await repo.get_friendship_by_id(session, friendship_id, lock=True)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Friend request not found"
        )
    if row.addressee_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the recipient can respond to this friend request",
        )
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Friend request is no longer pending",
        )
    if new_status == "accepted" and await repo.get_active_user(session, row.requester_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return await repo.set_friendship_status(session, row, new_status)


async def accept_request(session: AsyncSession, *, friendship_id: int, user_id: int) -> Friendship:
    """Accept an incoming pending friend request."""
    return await _respond_to_request(
        session, friendship_id=friendship_id, user_id=user_id, new_status="accepted"
    )


async def decline_request(session: AsyncSession, *, friendship_id: int, user_id: int) -> Friendship:
    """Decline an incoming pending friend request."""
    return await _respond_to_request(
        session, friendship_id=friendship_id, user_id=user_id, new_status="declined"
    )


async def remove_friend(session: AsyncSession, *, friendship_id: int, user_id: int) -> None:
    """Remove an accepted friendship or cancel a pending request as a participant."""
    row = await repo.get_friendship_by_id(session, friendship_id, lock=True)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Friendship not found")
    if user_id not in (row.requester_id, row.addressee_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to remove this friendship",
        )
    if row.status not in ("pending", "accepted"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Friendship not found")

    await repo.delete_friendship(session, row)


async def list_friends(
    session: AsyncSession,
    redis: Redis,
    storage: Storage,
    *,
    user_id: int,
) -> list[FriendOut]:
    """Return active accepted friends from one SQL join plus one Redis presence pipeline."""
    rows = await repo.list_accepted_friends(session, user_id)
    online_ids = await realtime_service.online_user_ids(redis, [uid for uid, *_ in rows])
    return [
        FriendOut(
            user_id=uid,
            first_name=first_name,
            last_name=last_name,
            position=position,
            avatar_object_key=avatar_key,
            avatar_url=storage.avatar_url(avatar_key),
            is_online=uid in online_ids,
        )
        for uid, first_name, last_name, position, avatar_key in rows
    ]


async def get_public_profile(
    session: AsyncSession,
    redis: Redis,
    storage: Storage,
    *,
    viewer_id: int,
    target_user_id: int,
) -> PublicProfileOut:
    """Return another (or current) active user's public profile, presence, and relation."""
    target = await repo.get_active_user(session, target_user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    friendship_status: FriendshipStatusView | None = None
    if target_user_id != viewer_id:
        rel = await repo.get_live_friendship_for_pair(session, viewer_id, target_user_id)
        if rel is not None:
            if rel.status == "accepted":
                friendship_status = "accepted"
            else:
                friendship_status = (
                    "pending_sent" if rel.requester_id == viewer_id else "pending_received"
                )

    online = await realtime_service.is_online(redis, target_user_id)
    return PublicProfileOut(
        id=target.id,
        first_name=target.first_name,
        last_name=target.last_name,
        position=target.position,
        bio=target.bio,
        avatar_object_key=target.avatar_object_key,
        avatar_url=storage.avatar_url(target.avatar_object_key),
        is_online=online,
        friendship_status=friendship_status,
    )
