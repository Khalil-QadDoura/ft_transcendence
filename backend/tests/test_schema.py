"""The database schema, checked on a real PostgreSQL with PostGIS.

These tests run `alembic downgrade base`, which deletes every table, so they use their own
database: TEST_DATABASE_URL, whose name must contain "test". Without one they are skipped.
To run them:

    docker run -d --name wozu-test-db -p 5432:5432 -e POSTGRES_PASSWORD=test \
        -e POSTGRES_DB=wozu_test postgis/postgis:15-3.4
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:5432/wozu_test pytest -q
"""

import pytest
from conftest import TEST_DATABASE_URL, alembic, needs_database
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.applications.models import Application
from app.companies.models import Company
from app.conversations.models import Conversation, ConversationParticipant, Message
from app.friends.models import Friendship
from app.game.models import GameParticipant, GameRoom, GameVote
from app.jobs.models import Job
from app.media.models import IntroVideo
from app.users.models import User

SCHEMA_TABLES = {
    "users",
    "refresh_tokens",
    "password_reset_tokens",
    "friendships",
    "companies",
    "jobs",
    "intro_videos",
    "conversations",
    "conversation_participants",
    "messages",
    "applications",
    "application_events",
    "job_views",
    "game_rooms",
    "game_participants",
    "game_messages",
    "game_votes",
}
# Tables of the reference backend we do not port (legacy chat, resumes, anonymous drafts).
DROPPED_TABLES = {
    "chat_threads",
    "chat_messages",
    "resumes",
    "resume_experiences",
    "resume_educations",
    "resume_skills",
    "resume_languages",
    "draft_videos",
}
# Tables that are in the database but are not ours: Alembic's record of the applied
# migrations, and PostGIS's list of map projections.
BOOKKEEPING_TABLES = {"alembic_version", "spatial_ref_sys"}


pytestmark = [needs_database, pytest.mark.anyio]


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module", autouse=True)
def schema_at_head():
    """Build the schema once from an empty database for the tests in this file."""
    alembic("downgrade", "base")
    alembic("upgrade", "head")


async def query(sql: str, **params) -> list:
    """Run one SELECT on a fresh connection and return the first column of every row."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        values = list((await connection.execute(text(sql), params)).scalars())
    await engine.dispose()
    return values


async def our_tables() -> set[str]:
    names = await query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    return set(names) - BOOKKEEPING_TABLES


async def columns(table: str) -> set[str]:
    names = await query(
        "SELECT column_name FROM information_schema.columns WHERE table_name = :table",
        table=table,
    )
    return set(names)


@pytest.fixture
async def session():
    """A session for adding rows. It never commits, so its rows vanish after the test."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with AsyncSession(engine) as db_session:
        yield db_session
    await engine.dispose()


async def add(session: AsyncSession, row):
    """Insert one row now (not at commit), so the database checks it right away."""
    session.add(row)
    await session.flush()
    return row


# Building and removing the schema -------------------------------------------------------


async def test_upgrade_on_an_empty_database_creates_our_tables_and_nothing_else():
    alembic("downgrade", "base")
    assert await our_tables() == set()

    alembic("upgrade", "head")
    assert await our_tables() == SCHEMA_TABLES
    assert len(SCHEMA_TABLES) == 17


async def test_legacy_tables_are_not_created():
    assert DROPPED_TABLES.isdisjoint(await our_tables())


async def test_models_match_the_migration():
    """`alembic check` compares the models with the database and finds no difference."""
    assert "No new upgrade operations detected" in alembic("check")


async def test_downgrade_removes_every_table_and_type():
    alembic("downgrade", "base")
    try:
        assert await our_tables() == set()
        assert await query("SELECT typname FROM pg_type WHERE typtype = 'e'") == []
    finally:
        alembic("upgrade", "head")


# Accounts ---------------------------------------------------------------------------------


async def test_users_has_no_phone_or_username_columns():
    dropped = {"phone", "is_phone_verified", "deleted_phone", "username"}
    assert dropped.isdisjoint(await columns("users"))


async def test_user_email_is_unique(session):
    await add(session, User(email="ana@example.com"))
    with pytest.raises(IntegrityError, match="uq_users_email"):
        await add(session, User(email="ana@example.com"))


async def test_new_user_gets_the_defaults(session):
    user = await add(session, User(email="ana@example.com"))
    await session.refresh(user)
    assert (user.status, user.is_email_verified, user.token_version) == ("active", False, 1)


async def two_users(session: AsyncSession) -> tuple[int, int]:
    ana = await add(session, User(email="ana@example.com"))
    ben = await add(session, User(email="ben@example.com"))
    return ana.id, ben.id


# Friends ----------------------------------------------------------------------------------


async def test_a_pair_has_one_friendship_whoever_asked(session):
    ana, ben = await two_users(session)
    await add(session, Friendship(requester_id=ana, addressee_id=ben))
    with pytest.raises(IntegrityError, match="uq_friendships_pair"):
        await add(session, Friendship(requester_id=ben, addressee_id=ana))


async def test_a_declined_request_does_not_block_a_new_one(session):
    ana, ben = await two_users(session)
    await add(session, Friendship(requester_id=ana, addressee_id=ben, status="declined"))
    await add(session, Friendship(requester_id=ben, addressee_id=ana))


async def test_nobody_can_befriend_themselves(session):
    ana, _ = await two_users(session)
    with pytest.raises(IntegrityError, match="ck_friendships_not_self"):
        await add(session, Friendship(requester_id=ana, addressee_id=ana))


# Companies and jobs -------------------------------------------------------------------------


async def new_job(session: AsyncSession, **fields) -> Job:
    """A job of a new company; keyword arguments replace the default values."""
    owner = await add(session, User(email="boss@example.com"))
    company = await add(session, Company(owner_user_id=owner.id, name="Sea Cafe"))
    values = {
        "title": "Barista",
        "description": "Make coffee for our guests",
        "latitude": 24.4539,  # Abu Dhabi
        "longitude": 54.3773,
        "location": "Abu Dhabi",
        **fields,
    }
    return await add(session, Job(owner_id=company.id, **values))


async def test_an_owner_has_one_active_company(session):
    owner = await add(session, User(email="boss@example.com"))
    await add(session, Company(owner_user_id=owner.id, name="Old Cafe", status="deleted"))
    await add(session, Company(owner_user_id=owner.id, name="Sea Cafe"))
    with pytest.raises(IntegrityError, match="uq_companies_owner_active"):
        await add(session, Company(owner_user_id=owner.id, name="Second Cafe"))


async def test_job_status_is_draft_open_deleted_and_starts_as_draft(session):
    assert await query("SELECT unnest(enum_range(NULL::job_status))::text") == [
        "draft",
        "open",
        "deleted",
    ]
    job = await new_job(session)
    await session.refresh(job)
    assert job.status == "draft"


@pytest.mark.parametrize(
    ("field", "value", "check"),
    [
        ("latitude", 91, "ck_jobs_latitude_range"),
        ("longitude", -181, "ck_jobs_longitude_range"),
        ("salary_amount", -1, "ck_jobs_salary_not_negative"),
        ("salary_currency", "usd", "ck_jobs_currency_iso_4217"),
    ],
)
async def test_job_checks_reject_bad_values(session, field, value, check):
    with pytest.raises(IntegrityError, match=check):
        await new_job(session, **{field: value})


async def test_job_checks_accept_an_empty_salary(session):
    await new_job(session, salary_amount=None, salary_currency=None)


async def test_trigger_keeps_search_vector_up_to_date(session):
    job = await new_job(session)
    matches = text("SELECT search_vector @@ to_tsquery('english', :word) FROM jobs WHERE id = :id")

    assert await session.scalar(matches, {"word": "coffee", "id": job.id})
    job.description = "Cook breakfast"
    await session.flush()
    assert await session.scalar(matches, {"word": "breakfast", "id": job.id})
    assert not await session.scalar(matches, {"word": "coffee", "id": job.id})


async def test_location_point_follows_latitude_and_longitude(session):
    job = await new_job(session)
    within = text(
        "SELECT ST_DWithin(location_point, ST_MakePoint(55.2708, 25.2048)::geography, :meters) "
        "FROM jobs WHERE id = :id"
    )  # Dubai is about 123 km away
    assert await session.scalar(within, {"meters": 150_000, "id": job.id})
    assert not await session.scalar(within, {"meters": 100_000, "id": job.id})


async def test_jobs_have_a_gist_and_a_gin_index():
    definitions = await query("SELECT indexdef FROM pg_indexes WHERE tablename = 'jobs'")
    assert any("USING gist (location_point)" in d for d in definitions)
    assert any("USING gin (search_vector)" in d for d in definitions)


# Videos -----------------------------------------------------------------------------------


def video(user_id: int, number: int, **fields) -> IntroVideo:
    return IntroVideo(
        user_id=user_id,
        object_key=f"users/{user_id}/intro/{number}.mp4",
        duration_sec=30,
        size_bytes=1_000_000,
        content_type="video/mp4",
        **fields,
    )


async def test_moderation_status_includes_moderation_error():
    assert await query("SELECT unnest(enum_range(NULL::moderation_status))::text") == [
        "pending",
        "approved",
        "rejected",
        "moderation_error",
    ]


async def test_a_user_has_one_posted_video(session):
    ana = await add(session, User(email="ana@example.com"))
    await add(session, video(ana.id, 1, lifecycle_status="posted"))
    await add(session, video(ana.id, 2, lifecycle_status="unposted"))
    with pytest.raises(IntegrityError, match="uq_intro_videos_user_id_posted"):
        await add(session, video(ana.id, 3, lifecycle_status="posted"))


# Chat -------------------------------------------------------------------------------------


async def test_a_user_joins_a_conversation_once(session):
    ana, _ = await two_users(session)
    chat = await add(session, Conversation(type="direct"))
    await add(session, ConversationParticipant(conversation_id=chat.id, user_id=ana))
    with pytest.raises(
        IntegrityError, match="uq_conversation_participants_conversation_id_user_id"
    ):
        await add(session, ConversationParticipant(conversation_id=chat.id, user_id=ana))


async def test_a_retried_send_does_not_make_a_second_message(session):
    ana, _ = await two_users(session)
    chat = await add(session, Conversation(type="direct"))
    for _ in range(2):  # without a key, the same text twice is two messages
        await add(session, Message(conversation_id=chat.id, author_id=ana, content="Hi"))
    await add(session, Message(conversation_id=chat.id, content="Hi", idempotency_key="k1"))
    with pytest.raises(IntegrityError, match="uq_messages_conversation_id_idempotency_key"):
        await add(session, Message(conversation_id=chat.id, content="Hi", idempotency_key="k1"))


async def test_deleting_a_user_removes_their_memberships_but_keeps_their_messages(session):
    ana, _ = await two_users(session)
    chat = await add(session, Conversation(type="direct"))
    await add(session, ConversationParticipant(conversation_id=chat.id, user_id=ana))
    message = await add(session, Message(conversation_id=chat.id, author_id=ana, content="Hi"))

    await session.execute(delete(User).where(User.id == ana))

    memberships = select(func.count()).where(ConversationParticipant.user_id == ana)
    assert await session.scalar(memberships) == 0  # CASCADE
    author = select(Message.author_id).where(Message.id == message.id)
    assert await session.scalar(author) is None  # SET NULL


# Applications -----------------------------------------------------------------------------


async def test_a_person_applies_to_a_job_once(session):
    job = await new_job(session)
    ana = await add(session, User(email="ana@example.com"))
    await add(session, Application(job_id=job.id, applicant_id=ana.id, company_id=job.owner_id))
    with pytest.raises(IntegrityError, match="uq_applications_job_id_applicant_id"):
        await add(session, Application(job_id=job.id, applicant_id=ana.id, company_id=job.owner_id))


async def test_an_application_and_its_conversation_point_at_each_other(session):
    job = await new_job(session)
    ana = await add(session, User(email="ana@example.com"))
    chat = await add(session, Conversation(type="direct", job_id=job.id))
    application = await add(
        session,
        Application(
            job_id=job.id, applicant_id=ana.id, company_id=job.owner_id, conversation_id=chat.id
        ),
    )
    chat.application_id = application.id
    await session.flush()

    await session.execute(delete(Application).where(Application.id == application.id))
    link = select(Conversation.application_id).where(Conversation.id == chat.id)
    assert await session.scalar(link) is None  # SET NULL: the chat stays


# Game -------------------------------------------------------------------------------------


async def test_a_person_joins_a_room_once_but_a_room_can_have_several_bots(session):
    ana, _ = await two_users(session)
    room = await add(session, GameRoom(target_size=3))
    await add(session, GameParticipant(room_id=room.id, display_label="Player 1"))
    await add(session, GameParticipant(room_id=room.id, display_label="Player 2"))
    await add(session, GameParticipant(room_id=room.id, user_id=ana, display_label="Player 3"))
    with pytest.raises(IntegrityError, match="uq_game_participants_room_id_user_id"):
        await add(session, GameParticipant(room_id=room.id, user_id=ana, display_label="P4"))


async def two_bots(session: AsyncSession) -> tuple[int, int, int]:
    """A room with two bots in it; returns the ids of the room and of the two bots."""
    room = await add(session, GameRoom(target_size=3))
    one = await add(session, GameParticipant(room_id=room.id, display_label="Player 1"))
    two = await add(session, GameParticipant(room_id=room.id, display_label="Player 2"))
    return room.id, one.id, two.id


def vote(room: int, voter: int, target: int, guess: str) -> GameVote:
    return GameVote(
        room_id=room, voter_participant_id=voter, target_participant_id=target, guess=guess
    )


async def test_a_player_guesses_once_about_each_other_player(session):
    room, one, two = await two_bots(session)
    await add(session, vote(room, one, two, "bot"))
    unique_pair = "uq_game_votes_voter_participant_id_target_participant_id"
    with pytest.raises(IntegrityError, match=unique_pair):
        await add(session, vote(room, one, two, "human"))


async def test_a_player_cannot_vote_about_themselves(session):
    room, one, _ = await two_bots(session)
    with pytest.raises(IntegrityError, match="ck_game_votes_not_self"):
        await add(session, vote(room, one, one, "bot"))
