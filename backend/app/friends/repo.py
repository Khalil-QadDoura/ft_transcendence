"""Database queries for friends and public profiles. No HTTP, no business rules."""

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.friends.models import Friendship
from app.users.models import User


async def get_active_user(session: AsyncSession, user_id: int) -> User | None:
    """Return an active (non-deleted) user by ID."""
    stmt = select(User).where(User.id == user_id, User.status == "active")
    return await session.scalar(stmt)


async def get_live_friendship_for_pair(
    session: AsyncSession, user_a: int, user_b: int
) -> Friendship | None:
    """Return the active pending or accepted friendship between two users, if any."""
    low, high = min(user_a, user_b), max(user_a, user_b)
    stmt = select(Friendship).where(
        func.least(Friendship.requester_id, Friendship.addressee_id) == low,
        func.greatest(Friendship.requester_id, Friendship.addressee_id) == high,
        Friendship.status.in_(("pending", "accepted")),
    )
    return await session.scalar(stmt)


async def create_friend_request(
    session: AsyncSession, requester_id: int, addressee_id: int
) -> Friendship:
    """Persist a new pending friend request and return the refreshed row."""
    row = Friendship(requester_id=requester_id, addressee_id=addressee_id, status="pending")
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_incoming_requests(session: AsyncSession, user_id: int) -> list[Friendship]:
    """Return incoming pending friend requests from active users, newest first."""
    stmt = (
        select(Friendship)
        .join(User, User.id == Friendship.requester_id)
        .where(
            Friendship.addressee_id == user_id,
            Friendship.status == "pending",
            User.status == "active",
        )
        .order_by(Friendship.created_at.desc(), Friendship.id.desc())
    )
    return list((await session.scalars(stmt)).all())


async def get_friendship_by_id(
    session: AsyncSession, friendship_id: int, *, lock: bool = False
) -> Friendship | None:
    """Fetch a friendship row by ID, optionally locking and refreshing from DB."""
    stmt = select(Friendship).where(Friendship.id == friendship_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(stmt)


async def set_friendship_status(
    session: AsyncSession, friendship: Friendship, status: str
) -> Friendship:
    """Persist a status change on a friendship row and return the refreshed row."""
    friendship.status = status
    await session.commit()
    await session.refresh(friendship)
    return friendship


async def delete_friendship(session: AsyncSession, friendship: Friendship) -> None:
    """Delete a friendship row and commit."""
    await session.delete(friendship)
    await session.commit()


async def list_accepted_friends(
    session: AsyncSession, user_id: int
) -> list[tuple[int, int, str | None, str | None, str | None, str | None]]:
    """Fetch active accepted friends in a single SQL join (no N+1 queries)."""
    peer_id_expr = case(
        (Friendship.requester_id == user_id, Friendship.addressee_id),
        else_=Friendship.requester_id,
    )
    stmt = (
        select(
            Friendship.id,
            User.id,
            User.first_name,
            User.last_name,
            User.position,
            User.avatar_object_key,
        )
        .select_from(Friendship)
        .join(User, User.id == peer_id_expr)
        .where(
            Friendship.status == "accepted",
            or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
            User.status == "active",
        )
        .order_by(User.first_name.asc().nulls_last(), User.last_name.asc().nulls_last(), User.id)
    )
    return [tuple(row) for row in (await session.execute(stmt)).all()]
