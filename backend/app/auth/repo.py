"""Database queries of sign-up and login: users and their refresh tokens. No HTTP, no rules."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


def add_user(session: AsyncSession, email: str) -> User:
    """A new account, saved with the next commit."""
    user = User(email=email)
    session.add(user)
    return user
