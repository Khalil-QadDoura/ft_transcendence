"""Database queries of /api/media: the intro_videos table, and for the feed the companies, jobs
and applications tables. No HTTP, no rules."""

from sqlalchemy import and_, case, exists, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application
from app.companies.models import Company
from app.jobs.models import Job
from app.media.constants import (
    EMPLOYER_FEED_RATINGS,
    MP4_CONTENT_TYPE,
    WAITING_APPLICATION_STATUSES,
)
from app.media.models import IntroVideo
from app.users.models import User


async def lock_user(session: AsyncSession, user_id: int) -> None:
    """Lock the user's row in users (SELECT ... FOR UPDATE) until this transaction ends, at
    commit or rollback. Another request that asks for the same lock waits here until then."""
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())


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


async def owns_active_company(session: AsyncSession, user_id: int) -> bool:
    """True for an employer: a user who owns a company that is not deleted."""
    return await session.scalar(
        select(exists().where(Company.owner_user_id == user_id, Company.status == "active"))
    )


def feed_group(job_id: int | None):
    """The feed's groups, as an SQL expression; group 1 is shown first. For a job:
    1 = applied to it and still waiting for an answer, 2 = position contains the job's title
    (ILIKE: big and small letters alike), 3 = everyone else. Without a job: all in group 3."""
    if job_id is None:
        return literal(3)
    applied = exists().where(
        Application.job_id == job_id,
        Application.applicant_id == IntroVideo.user_id,
        Application.status.in_(WAITING_APPLICATION_STATUSES),
    )
    job_title = select(Job.title).where(Job.id == job_id).scalar_subquery()
    return case((applied, 1), (User.position.ilike("%" + job_title + "%"), 2), else_=3)


async def feed_group_of(session: AsyncSession, video_id: int, job_id: int | None) -> int | None:
    """The group of one video (the last one of the page before), None if there is no such video."""
    return await session.scalar(
        select(feed_group(job_id))
        .select_from(IntroVideo)
        .join(User, User.id == IntroVideo.user_id)
        .where(IntroVideo.id == video_id)
    )


async def list_feed(
    session: AsyncSession,
    job_id: int | None,
    employer: bool,
    after: tuple[int | None, int] | None,
    limit: int,
) -> list:
    """Approved and posted videos of active accounts, with their author: by group, then newest
    first. after = (group, id) of the last video already shown; the list goes on after it."""
    group = feed_group(job_id)
    query = (
        select(IntroVideo, User.first_name, User.last_name, User.position)
        .join(User, User.id == IntroVideo.user_id)
        .where(
            IntroVideo.moderation_status == "approved",
            IntroVideo.lifecycle_status == "posted",
            User.status == "active",  # a deleted account's video is never shown
        )
        .order_by(group, IntroVideo.id.desc())
        .limit(limit)
    )
    if employer:
        query = query.where(IntroVideo.video_rating.in_(EMPLOYER_FEED_RATINGS))
    if after is not None:
        # What comes after the last video shown: a later group, or the same group, older.
        after_group, after_id = after
        query = query.where(
            or_(group > after_group, and_(group == after_group, IntroVideo.id < after_id))
        )
    return list(await session.execute(query))
