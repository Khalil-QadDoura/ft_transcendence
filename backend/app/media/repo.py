"""Database queries of /api/media: the intro_videos table. No HTTP, no rules."""

from sqlalchemy import func, select, update
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


async def get_my_video(session: AsyncSession, user_id: int, video_id: int) -> IntroVideo | None:
    """One of the user's videos, or None if it does not exist, is someone else's or is deleted."""
    return await session.scalar(
        select(IntroVideo).where(
            IntroVideo.id == video_id,
            IntroVideo.user_id == user_id,
            IntroVideo.lifecycle_status != "deleted",
        )
    )


async def list_my_videos(session: AsyncSession, user_id: int) -> list[IntroVideo]:
    """The user's videos that are not deleted, newest first."""
    result = await session.scalars(
        select(IntroVideo)
        .where(IntroVideo.user_id == user_id, IntroVideo.lifecycle_status != "deleted")
        .order_by(IntroVideo.id.desc())
    )
    return list(result)


async def unpost_posted_video(session: AsyncSession, user_id: int) -> None:
    """The user's posted video, if there is one, goes back to "unposted"."""
    await session.execute(
        update(IntroVideo)
        .where(IntroVideo.user_id == user_id, IntroVideo.lifecycle_status == "posted")
        .values(lifecycle_status="unposted")
    )
