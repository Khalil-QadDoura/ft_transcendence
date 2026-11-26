"""Idempotent demo seed & reset runner for BE-32."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import redis as redis_sync
import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.applications.models import Application, ApplicationEvent, JobView
from app.auth import security
from app.companies.models import Company
from app.conversations.models import Conversation, ConversationParticipant, Message
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.queue import TaskQueue
from app.core.storage import Storage
from app.friends.models import Friendship
from app.jobs.models import Job
from app.media.constants import (
    AVATARS_FOLDER,
    LOGOS_FOLDER,
    MP4_CONTENT_TYPE,
    VIDEOS_FOLDER,
)
from app.media.models import IntroVideo
from app.seed.data import (
    DEMO_APPLICATIONS,
    DEMO_CANDIDATES,
    DEMO_CONVERSATIONS,
    DEMO_EMPLOYERS,
    DEMO_FRIENDSHIPS,
    DEMO_JOBS,
    DEMO_PASSWORD,
    CandidateSpec,
    ConversationSpec,
    EmployerSpec,
    JobSpec,
)
from app.seed.media_assets import DEMO_VIDEO_DURATION_SEC, load_demo_video, render_badge_png
from app.users.models import User

log = structlog.get_logger(__name__)

# Status progression paths for realistic ApplicationEvent audit trails.
_STATUS_STEPS: dict[str, tuple[str, ...]] = {
    "submitted": ("submitted",),
    "viewed": ("submitted", "viewed"),
    "shortlisted": ("submitted", "viewed", "shortlisted"),
    "contacted": ("submitted", "viewed", "shortlisted", "contacted"),
    "hired": ("submitted", "viewed", "shortlisted", "contacted", "hired"),
    "rejected": ("submitted", "viewed", "rejected"),
}

_RESET_TABLES = (
    "game_votes",
    "game_messages",
    "game_participants",
    "game_rooms",
    "messages",
    "conversation_participants",
    "conversations",
    "application_events",
    "applications",
    "job_views",
    "jobs",
    "companies",
    "intro_videos",
    "friendships",
    "password_reset_tokens",
    "refresh_tokens",
    "users",
)

_RESET_MINIO_PREFIXES = ("avatars/", "logos/", "videos/", "users/", "staging/")
_RESET_REDIS_PATTERNS = ("ws:*", "game:*", "presence:*", "rate:*", "job_view:*", "oauth:*")


@dataclass(frozen=True)
class SeedSummary:
    """Counts of entities present and newly created during a seed run."""

    users_created: int = 0
    companies_created: int = 0
    jobs_created: int = 0
    videos_created: int = 0
    applications_created: int = 0
    friendships_created: int = 0
    conversations_created: int = 0
    messages_created: int = 0
    moderation_queued: int = 0


def _deterministic_uuid(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"wozu.seed.{label}"))


def _ensure_object(storage: Storage, key: str, data: bytes, content_type: str) -> None:
    if storage.stat(key) is None:
        storage.put(key, data, content_type)


async def _ensure_user(
    session: AsyncSession,
    storage: Storage,
    *,
    email: str,
    first_name: str,
    last_name: str,
    position: str,
    bio: str,
    avatar_bg: tuple[int, int, int],
    password_hash: str,
) -> tuple[User, bool]:
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    created = False
    if existing is None:
        user = User(
            email=email,
            password_hash=password_hash,
            is_email_verified=True,
            first_name=first_name,
            last_name=last_name,
            position=position,
            bio=bio,
            status="active",
        )
        session.add(user)
        await session.flush()
    else:
        user = existing

    if user.avatar_object_key is None:
        user.avatar_object_key = f"{AVATARS_FOLDER}/{user.id}/{_deterministic_uuid(email)}.png"
        created = existing is None

    monogram = f"{first_name[:1]}{last_name[:1]}"
    _ensure_object(
        storage,
        user.avatar_object_key,
        render_badge_png(monogram, avatar_bg, rounded=False),
        "image/png",
    )
    return user, existing is None or created


async def _ensure_company(
    session: AsyncSession,
    storage: Storage,
    owner: User,
    spec: EmployerSpec,
) -> tuple[Company, bool]:
    existing = (
        await session.execute(
            select(Company).where(
                Company.owner_user_id == owner.id,
                Company.status == "active",
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        company = Company(
            owner_user_id=owner.id,
            name=spec.company_name,
            description=spec.company_description,
            status="active",
            country=spec.country,
            country_code=spec.country_code,
            city=spec.city,
            district=spec.district,
        )
        session.add(company)
        await session.flush()
    else:
        company = existing

    if company.logo_object_key is None:
        company.logo_object_key = (
            f"{LOGOS_FOLDER}/{company.id}/{_deterministic_uuid(spec.company_name)}.png"
        )

    _ensure_object(
        storage,
        company.logo_object_key,
        render_badge_png(spec.logo_monogram, spec.logo_bg, rounded=True),
        "image/png",
    )
    return company, existing is None


async def _ensure_candidate_videos(
    session: AsyncSession,
    storage: Storage,
    user: User,
    spec: CandidateSpec,
) -> tuple[IntroVideo, int]:
    """Ensure the candidate has an approved+posted pitch video (and optional rejected video)."""
    created = 0
    posted = (
        await session.execute(
            select(IntroVideo).where(
                IntroVideo.user_id == user.id,
                IntroVideo.lifecycle_status == "posted",
            )
        )
    ).scalar_one_or_none()

    video_bytes = load_demo_video(spec.video_asset)
    if posted is None:
        key = f"{VIDEOS_FOLDER}/{user.id}/{_deterministic_uuid(f'{spec.email}.posted')}.mp4"
        _ensure_object(storage, key, video_bytes, MP4_CONTENT_TYPE)
        posted = IntroVideo(
            user_id=user.id,
            object_key=key,
            duration_sec=DEMO_VIDEO_DURATION_SEC,
            size_bytes=len(video_bytes),
            content_type=MP4_CONTENT_TYPE,
            moderation_status="approved",
            lifecycle_status="posted",
            video_rating=spec.video_rating,
        )
        session.add(posted)
        await session.flush()
        created += 1
    else:
        _ensure_object(storage, posted.object_key, video_bytes, MP4_CONTENT_TYPE)

    if spec.include_rejected_video:
        rejected = (
            await session.execute(
                select(IntroVideo).where(
                    IntroVideo.user_id == user.id,
                    IntroVideo.moderation_status == "rejected",
                )
            )
        ).scalar_one_or_none()
        if rejected is None:
            rej_bytes = load_demo_video("demo_intro_3.mp4")
            rej_key = (
                f"{VIDEOS_FOLDER}/{user.id}/{_deterministic_uuid(f'{spec.email}.rejected')}.mp4"
            )
            _ensure_object(storage, rej_key, rej_bytes, MP4_CONTENT_TYPE)
            session.add(
                IntroVideo(
                    user_id=user.id,
                    object_key=rej_key,
                    duration_sec=DEMO_VIDEO_DURATION_SEC,
                    size_bytes=len(rej_bytes),
                    content_type=MP4_CONTENT_TYPE,
                    moderation_status="rejected",
                    rejected_reason="Sample demo rejection for My Videos UI showcase.",
                    lifecycle_status="loaded",
                    video_rating="C",
                )
            )
            await session.flush()
            created += 1

    return posted, created


async def _ensure_job(
    session: AsyncSession,
    company: Company,
    spec: JobSpec,
) -> tuple[Job, bool]:
    existing = (
        await session.execute(
            select(Job).where(
                Job.owner_id == company.id,
                Job.title == spec.title,
                Job.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    job = Job(
        owner_id=company.id,
        title=spec.title,
        description=spec.description,
        status=spec.status,
        latitude=spec.latitude,
        longitude=spec.longitude,
        location=spec.location,
        salary_amount=spec.salary_amount,
        salary_type=spec.salary_type,
        salary_currency=spec.salary_currency,
        schedule=spec.schedule,
        urgency=spec.urgency,
    )
    session.add(job)
    await session.flush()
    return job, True


async def _ensure_application(
    session: AsyncSession,
    *,
    job: Job,
    company: Company,
    applicant: User,
    employer: User,
    intro_video: IntroVideo,
    status_name: str,
    cover_note: str,
    status_note: str | None,
) -> tuple[Application, bool]:
    existing = (
        await session.execute(
            select(Application).where(
                Application.job_id == job.id,
                Application.applicant_id == applicant.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    now = datetime.now(UTC)
    viewed_at = None if status_name == "submitted" else now
    app_row = Application(
        job_id=job.id,
        applicant_id=applicant.id,
        company_id=company.id,
        intro_video_id=intro_video.id,
        status=status_name,
        cover_note=cover_note,
        applied_at=now,
        viewed_at=viewed_at,
    )
    session.add(app_row)
    await session.flush()

    steps = _STATUS_STEPS[status_name]
    for idx, to_status in enumerate(steps):
        from_status = None if idx == 0 else steps[idx - 1]
        actor_id = applicant.id if idx == 0 else employer.id
        note = status_note if idx == len(steps) - 1 else None
        session.add(
            ApplicationEvent(
                application_id=app_row.id,
                actor_id=actor_id,
                from_status=from_status,
                to_status=to_status,
                note=note,
            )
        )

    # Seed realistic initial views for jobs that received applications if none recorded yet.
    view_count = (
        await session.execute(select(func.count(JobView.id)).where(JobView.job_id == job.id))
    ).scalar_one()
    if view_count == 0:
        session.add(JobView(job_id=job.id, viewer_id=applicant.id, viewed_at=now))

    await session.flush()
    return app_row, True


async def _ensure_friendship(
    session: AsyncSession,
    requester: User,
    addressee: User,
    status_name: str,
) -> bool:
    existing = (
        await session.execute(
            select(Friendship).where(
                func.least(Friendship.requester_id, Friendship.addressee_id)
                == min(requester.id, addressee.id),
                func.greatest(Friendship.requester_id, Friendship.addressee_id)
                == max(requester.id, addressee.id),
                Friendship.status.in_(("pending", "accepted")),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    session.add(
        Friendship(
            requester_id=requester.id,
            addressee_id=addressee.id,
            status=status_name,
        )
    )
    await session.flush()
    return True


async def _ensure_conversation(
    session: AsyncSession,
    spec: ConversationSpec,
    users_by_email: dict[str, User],
    apps_by_key: dict[tuple[str, str], Application],
    jobs_by_title: dict[str, Job],
) -> tuple[bool, int]:
    user_a = users_by_email[spec.participant_emails[0]]
    user_b = users_by_email[spec.participant_emails[1]]
    linked_app = (
        apps_by_key.get((spec.linked_applicant_email, spec.linked_job_title))
        if spec.linked_applicant_email and spec.linked_job_title
        else None
    )
    linked_job = jobs_by_title.get(spec.linked_job_title) if spec.linked_job_title else None

    conv: Conversation | None = None
    if linked_app is not None and linked_app.conversation_id is not None:
        conv = await session.get(Conversation, linked_app.conversation_id)
    if conv is None:
        p1 = select(ConversationParticipant.conversation_id).where(
            ConversationParticipant.user_id == user_a.id
        )
        p2 = select(ConversationParticipant.conversation_id).where(
            ConversationParticipant.user_id == user_b.id
        )
        conv = (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.type == "direct",
                    Conversation.id.in_(p1),
                    Conversation.id.in_(p2),
                )
                .order_by(Conversation.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    created_conv = conv is None
    if conv is None:
        conv = Conversation(
            type="direct",
            title=spec.title,
            job_id=linked_job.id if linked_job is not None else None,
            application_id=linked_app.id if linked_app is not None else None,
        )
        session.add(conv)
        await session.flush()

        for uid in (user_a.id, user_b.id):
            session.add(
                ConversationParticipant(
                    conversation_id=conv.id,
                    user_id=uid,
                    role="member",
                    is_muted=False,
                )
            )
        await session.flush()

    if linked_app is not None and linked_app.conversation_id is None:
        linked_app.conversation_id = conv.id

    msgs_created = 0
    msg_ids: list[int] = []
    for msg_spec in spec.messages:
        idem_key = f"seed:{spec.key}:{msg_spec.key_suffix}"
        existing_msg = (
            await session.execute(
                select(Message).where(
                    and_(
                        Message.conversation_id == conv.id,
                        Message.idempotency_key == idem_key,
                    )
                )
            )
        ).scalar_one_or_none()
        if existing_msg is not None:
            msg_ids.append(existing_msg.id)
            continue

        sender = users_by_email[msg_spec.sender_email]
        is_unread = spec.unread_for_email is not None and msg_spec == spec.messages[-1]
        msg = Message(
            conversation_id=conv.id,
            author_id=sender.id,
            content=msg_spec.content,
            status="delivered" if is_unread else "read",
            idempotency_key=idem_key,
            message_type="text",
        )
        session.add(msg)
        await session.flush()
        msg_ids.append(msg.id)
        msgs_created += 1

    if msg_ids and conv.last_message_id is None:
        conv.last_message_id = msg_ids[-1]
    if msg_ids and created_conv:
        for email in spec.participant_emails:
            part = (
                await session.execute(
                    select(ConversationParticipant).where(
                        ConversationParticipant.conversation_id == conv.id,
                        ConversationParticipant.user_id == users_by_email[email].id,
                    )
                )
            ).scalar_one()
            if spec.unread_for_email == email and len(msg_ids) >= 2:
                part.last_read_message_id = msg_ids[-2]
            elif spec.unread_for_email != email:
                part.last_read_message_id = msg_ids[-1]

    await session.flush()
    return created_conv, msgs_created


async def _maybe_queue_live_moderation(
    session: AsyncSession,
    storage: Storage,
    candidate: User,
    enqueue_fn: Callable[[int, str], object],
) -> int:
    """Optionally upload a fresh sample pitch and enqueue it to test live moderation."""
    pending_key = f"{VIDEOS_FOLDER}/{candidate.id}/{_deterministic_uuid('live-moderation')}.mp4"
    existing = (
        await session.execute(select(IntroVideo).where(IntroVideo.object_key == pending_key))
    ).scalar_one_or_none()
    if existing is not None:
        return 0

    video_bytes = load_demo_video("demo_intro_2.mp4")
    _ensure_object(storage, pending_key, video_bytes, MP4_CONTENT_TYPE)
    video = IntroVideo(
        user_id=candidate.id,
        object_key=pending_key,
        duration_sec=DEMO_VIDEO_DURATION_SEC,
        size_bytes=len(video_bytes),
        content_type=MP4_CONTENT_TYPE,
        moderation_status="pending",
        lifecycle_status="loaded",
        video_rating="B",
    )
    session.add(video)
    await session.flush()
    enqueue_fn(video.id, video.object_key)
    return 1


async def seed_demo(
    session: AsyncSession,
    storage: Storage,
    *,
    moderate: bool = False,
    enqueue_fn: Callable[[int, str], object] | None = None,
    settings: Settings | None = None,
) -> SeedSummary:
    """Idempotently populate the database and MinIO bucket with demo data."""
    cfg = settings or get_settings()
    password_hash = security.hash_password(DEMO_PASSWORD)

    users_created = 0
    companies_created = 0
    jobs_created = 0
    videos_created = 0
    applications_created = 0
    friendships_created = 0
    conversations_created = 0
    messages_created = 0
    moderation_queued = 0

    users_by_email: dict[str, User] = {}
    companies_by_owner_email: dict[str, Company] = {}
    employer_by_company_id: dict[int, User] = {}
    videos_by_email: dict[str, IntroVideo] = {}

    for emp in DEMO_EMPLOYERS:
        user, u_created = await _ensure_user(
            session,
            storage,
            email=emp.email,
            first_name=emp.first_name,
            last_name=emp.last_name,
            position=emp.position,
            bio=emp.bio,
            avatar_bg=emp.avatar_bg,
            password_hash=password_hash,
        )
        users_by_email[emp.email] = user
        users_created += int(u_created)

        company, c_created = await _ensure_company(session, storage, user, emp)
        companies_by_owner_email[emp.email] = company
        employer_by_company_id[company.id] = user
        companies_created += int(c_created)

    for cand in DEMO_CANDIDATES:
        user, u_created = await _ensure_user(
            session,
            storage,
            email=cand.email,
            first_name=cand.first_name,
            last_name=cand.last_name,
            position=cand.position,
            bio=cand.bio,
            avatar_bg=cand.avatar_bg,
            password_hash=password_hash,
        )
        users_by_email[cand.email] = user
        users_created += int(u_created)

        posted_video, vids_new = await _ensure_candidate_videos(session, storage, user, cand)
        videos_by_email[cand.email] = posted_video
        videos_created += vids_new

    jobs_by_title: dict[str, Job] = {}
    for job_spec in DEMO_JOBS:
        company = companies_by_owner_email[job_spec.employer_email]
        job, j_created = await _ensure_job(session, company, job_spec)
        jobs_by_title[job.title] = job
        jobs_created += int(j_created)

    apps_by_key: dict[tuple[str, str], Application] = {}
    for app_spec in DEMO_APPLICATIONS:
        job = jobs_by_title[app_spec.job_title]
        company = next(c for c in companies_by_owner_email.values() if c.id == job.owner_id)
        employer = employer_by_company_id[company.id]
        applicant = users_by_email[app_spec.applicant_email]
        app_row, a_created = await _ensure_application(
            session,
            job=job,
            company=company,
            applicant=applicant,
            employer=employer,
            intro_video=videos_by_email[app_spec.applicant_email],
            status_name=app_spec.status,
            cover_note=app_spec.cover_note,
            status_note=app_spec.status_note,
        )
        apps_by_key[(app_spec.applicant_email, app_spec.job_title)] = app_row
        applications_created += int(a_created)

    for friend_spec in DEMO_FRIENDSHIPS:
        f_created = await _ensure_friendship(
            session,
            users_by_email[friend_spec.requester_email],
            users_by_email[friend_spec.addressee_email],
            friend_spec.status,
        )
        friendships_created += int(f_created)

    for conv_spec in DEMO_CONVERSATIONS:
        c_created, m_created = await _ensure_conversation(
            session,
            conv_spec,
            users_by_email,
            apps_by_key,
            jobs_by_title,
        )
        conversations_created += int(c_created)
        messages_created += m_created

    if moderate and cfg.openai_api_key:
        queue_cb = enqueue_fn or TaskQueue(cfg).moderate_video
        moderation_queued += await _maybe_queue_live_moderation(
            session,
            storage,
            users_by_email[DEMO_CANDIDATES[1].email],
            queue_cb,
        )

    await session.commit()
    summary = SeedSummary(
        users_created=users_created,
        companies_created=companies_created,
        jobs_created=jobs_created,
        videos_created=videos_created,
        applications_created=applications_created,
        friendships_created=friendships_created,
        conversations_created=conversations_created,
        messages_created=messages_created,
        moderation_queued=moderation_queued,
    )
    log.info("demo seed complete", **summary.__dict__)
    return summary


async def reset_demo(
    session: AsyncSession,
    storage: Storage,
    *,
    redis_client: redis_sync.Redis | None = None,
    moderate: bool = False,
    enqueue_fn: Callable[[int, str], object] | None = None,
    settings: Settings | None = None,
) -> SeedSummary:
    """Truncate demo tables, clear uploaded media objects and transient keys, then re-seed."""
    await session.execute(text(f"TRUNCATE {', '.join(_RESET_TABLES)} RESTART IDENTITY CASCADE"))
    await session.commit()

    for prefix in _RESET_MINIO_PREFIXES:
        for key in storage.keys_in(prefix):
            storage.remove(key)

    if redis_client is not None:
        for pattern in _RESET_REDIS_PATTERNS:
            for key in redis_client.scan_iter(pattern):
                redis_client.delete(key)

    return await seed_demo(
        session,
        storage,
        moderate=moderate,
        enqueue_fn=enqueue_fn,
        settings=settings,
    )


async def _run_cli(*, reset: bool, moderate: bool, settings: Settings | None = None) -> SeedSummary:
    cfg = settings or get_settings()
    engine = create_async_engine(cfg.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    storage = Storage(cfg)
    rclient: redis_sync.Redis | None = None
    try:
        async with session_factory() as session:
            if reset:
                rclient = redis_sync.Redis.from_url(cfg.redis_url, decode_responses=True)
                return await reset_demo(
                    session,
                    storage,
                    redis_client=rclient,
                    moderate=moderate,
                    settings=cfg,
                )
            return await seed_demo(session, storage, moderate=moderate, settings=cfg)
    finally:
        if rclient is not None:
            rclient.close()
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for `make seed` and `make reset-demo`."""
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description="Idempotently seed demo accounts, companies, jobs, videos and chats.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate app tables, wipe demo media objects and re-seed from scratch.",
    )
    parser.add_argument(
        "--moderate",
        action="store_true",
        help=(
            "Also upload a pending sample video and enqueue Celery moderation "
            "when OPENAI_API_KEY is set."
        ),
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    summary = asyncio.run(_run_cli(reset=args.reset, moderate=args.moderate, settings=settings))
    action = "Reset and seeded" if args.reset else "Seeded"
    queued = summary.moderation_queued
    mod_note = f", +{queued} queued for moderation" if queued else ""
    print(
        f"{action} demo data: "
        f"+{summary.users_created} users, +{summary.companies_created} companies, "
        f"+{summary.jobs_created} jobs, +{summary.videos_created} videos, "
        f"+{summary.applications_created} applications, "
        f"+{summary.friendships_created} friendships, "
        f"+{summary.conversations_created} conversations, "
        f"+{summary.messages_created} messages{mod_note}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
