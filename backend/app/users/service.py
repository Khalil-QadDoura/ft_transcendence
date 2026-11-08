"""The rules of the profile. Routes call these functions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User
from app.users.schemas import UserUpdate


async def update_profile(session: AsyncSession, user: User, data: UserUpdate) -> User:
    """A partial update: change only the fields the client sent, and save them."""
    # exclude_unset keeps only the fields present in the request, e.g. {"bio": "Hi"}.
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    # SQLAlchemy writes one UPDATE with only the changed columns (and updated_at).
    await session.commit()
    return user
