"""Database queries of sign-up and login: users and their refresh tokens. No HTTP, no rules."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken
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


def add_refresh_token(
    session: AsyncSession, user_id: int, jti: str, token_version: int, expires_at: datetime
) -> None:
    """Remember a refresh token by its id (jti), saved with the next commit."""
    session.add(
        RefreshToken(user_id=user_id, jti=jti, token_version=token_version, expires_at=expires_at)
    )
