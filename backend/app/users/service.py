"""The rules of the profile. Routes call these functions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import Storage
from app.users.models import User
from app.users.schemas import UserOut, UserUpdate


def to_user_out(storage: Storage, user: User) -> UserOut:
    """The profile we send back. Every field is read from my row, except avatar_url: storage
    turns avatar_object_key into an address the browser can open."""
    return UserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        position=user.position,
        birth_date=user.birth_date,
        bio=user.bio,
        avatar_object_key=user.avatar_object_key,
        avatar_url=storage.avatar_url(user.avatar_object_key),
        is_email_verified=user.is_email_verified,
    )


async def update_profile(session: AsyncSession, user: User, data: UserUpdate) -> User:
    """A partial update: change only the fields the client sent, and save them."""
    # exclude_unset keeps only the fields present in the request, e.g. {"bio": "Hi"}.
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    # SQLAlchemy writes one UPDATE with only the changed columns (and updated_at).
    await session.commit()
    return user


async def delete_account(session: AsyncSession, user: User) -> None:
    """Soft delete: the row stays, only its status becomes "deleted".

    That one change is enough to lock the account: login (auth/service.py) and every
    protected request and refresh (auth/deps.py, auth/service.py) check that the status is
    "active", so the user's tokens stop working at once and logging in again gets 401.
    """
    user.status = "deleted"
    await session.commit()
