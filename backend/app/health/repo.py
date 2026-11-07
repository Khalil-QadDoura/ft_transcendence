"""Database queries only: no HTTP, no business rules."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def select_one(session: AsyncSession) -> None:
    await session.execute(text("SELECT 1"))
