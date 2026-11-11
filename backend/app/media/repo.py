"""Database queries of /api/media: the intro_videos table. No HTTP, no rules."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.media.constants import MP4_CONTENT_TYPE
from app.media.models import IntroVideo


async def count_active_videos(session: AsyncSession, user_id: int) -> int:
    """How many videos the user has that are not deleted."""
    return await session.scalar(
        select(func.count())
        .select_from(IntroVideo)
        .where(IntroVideo.user_id == user_id, IntroVideo.lifecycle_status != "deleted")
    )


def add_video(
    session: AsyncSession, user_id: int, object_key: str, duration_sec: int, size_bytes: int
) -> IntroVideo:
    """A new video, waiting for moderation and not shown yet; saved with the next commit."""
    video = IntroVideo(
        user_id=user_id,
        object_key=object_key,
        duration_sec=duration_sec,
        size_bytes=size_bytes,
        content_type=MP4_CONTENT_TYPE,
        moderation_status="pending",
        lifecycle_status="loaded",
    )
    session.add(video)
    return video
