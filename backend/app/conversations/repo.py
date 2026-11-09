"""Database queries for the conversations domain."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversations.models import Conversation, ConversationParticipant, Message

# ── Conversations ─────────────────────────────────────────────────────────────


async def create_conversation(
    session: AsyncSession,
    *,
    type: str,
    title: str | None = None,
    job_id: int | None = None,
) -> Conversation:
    """Create a new conversation record."""
    conv = Conversation(type=type, title=title, job_id=job_id)
    session.add(conv)
    await session.flush()
    return conv


async def get_conversation(session: AsyncSession, conv_id: int) -> Conversation | None:
    """Fetch conversation by ID."""
    return await session.get(Conversation, conv_id)


async def find_direct_conversation(
    session: AsyncSession, user1_id: int, user2_id: int
) -> Conversation | None:
    """Find existing active direct conversation between two users."""
    sub = (
        select(ConversationParticipant.conversation_id)
        .where(
            ConversationParticipant.user_id.in_([user1_id, user2_id]),
            ConversationParticipant.left_at.is_(None),
        )
        .group_by(ConversationParticipant.conversation_id)
        .having(func.count(ConversationParticipant.user_id) == 2)
    )
    q = select(Conversation).where(
        Conversation.id.in_(sub),
        Conversation.type == "direct",
    )
    return (await session.execute(q)).scalar_one_or_none()


async def update_last_message(session: AsyncSession, conv_id: int, message_id: int) -> None:
    """Update conversation pointer to the most recent message."""
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conv_id)
        .values(last_message_id=message_id, updated_at=func.now())
    )


async def list_conversations_for_user(
    session: AsyncSession, user_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    """List conversations for a user with unread counts and last message snippet."""
    query_with_jobs = text("""
        SELECT
            c.id,
            c.type,
            c.title,
            c.job_id,
            c.last_message_id,
            c.updated_at,
            cp.last_read_message_id,
            cp.is_muted,
            cp.role,
            j.title AS job_title,
            (
                SELECT COUNT(*) FROM messages m
                WHERE m.conversation_id = c.id
                  AND m.id > COALESCE(cp.last_read_message_id, 0)
                  AND m.deleted_at IS NULL
                  AND m.author_id IS DISTINCT FROM :user_id
            ) AS unread_count,
            (
                SELECT m2.content FROM messages m2
                WHERE m2.id = c.last_message_id
            ) AS last_message_content,
            (
                SELECT m2.author_id FROM messages m2
                WHERE m2.id = c.last_message_id
            ) AS last_message_author_id
        FROM conversations c
        JOIN conversation_participants cp
          ON cp.conversation_id = c.id AND cp.user_id = :user_id AND cp.left_at IS NULL
        LEFT JOIN jobs j ON j.id = c.job_id
        ORDER BY c.updated_at DESC
        LIMIT :limit
    """)

    query_without_jobs = text("""
        SELECT
            c.id,
            c.type,
            c.title,
            c.job_id,
            c.last_message_id,
            c.updated_at,
            cp.last_read_message_id,
            cp.is_muted,
            cp.role,
            NULL AS job_title,
            (
                SELECT COUNT(*) FROM messages m
                WHERE m.conversation_id = c.id
                  AND m.id > COALESCE(cp.last_read_message_id, 0)
                  AND m.deleted_at IS NULL
                  AND m.author_id IS DISTINCT FROM :user_id
            ) AS unread_count,
            (
                SELECT m2.content FROM messages m2
                WHERE m2.id = c.last_message_id
            ) AS last_message_content,
            (
                SELECT m2.author_id FROM messages m2
                WHERE m2.id = c.last_message_id
            ) AS last_message_author_id
        FROM conversations c
        JOIN conversation_participants cp
          ON cp.conversation_id = c.id AND cp.user_id = :user_id AND cp.left_at IS NULL
        ORDER BY c.updated_at DESC
        LIMIT :limit
    """)

    params = {"user_id": user_id, "limit": limit}
    try:
        rows = await session.execute(query_with_jobs, params)
    except ProgrammingError:
        rows = await session.execute(query_without_jobs, params)

    return [dict(r._mapping) for r in rows]


async def get_conversation_for_user(
    session: AsyncSession, conv_id: int, user_id: int
) -> dict[str, Any] | None:
    """Fetch single conversation with unread counts scoped to participant."""
    query_with_jobs = text("""
        SELECT
            c.id, c.type, c.title, c.job_id, c.last_message_id, c.updated_at,
            cp.last_read_message_id, cp.is_muted, cp.role,
            j.title AS job_title,
            (
                SELECT COUNT(*) FROM messages m
                WHERE m.conversation_id = c.id
                  AND m.id > COALESCE(cp.last_read_message_id, 0)
                  AND m.deleted_at IS NULL
                  AND m.author_id IS DISTINCT FROM :user_id
            ) AS unread_count,
            (SELECT m2.content FROM messages m2 WHERE m2.id = c.last_message_id)
                AS last_message_content,
            (SELECT m2.author_id FROM messages m2 WHERE m2.id = c.last_message_id)
                AS last_message_author_id
        FROM conversations c
        JOIN conversation_participants cp
          ON cp.conversation_id = c.id AND cp.user_id = :user_id AND cp.left_at IS NULL
        LEFT JOIN jobs j ON j.id = c.job_id
        WHERE c.id = :conv_id
    """)

    query_without_jobs = text("""
        SELECT
            c.id, c.type, c.title, c.job_id, c.last_message_id, c.updated_at,
            cp.last_read_message_id, cp.is_muted, cp.role,
            NULL AS job_title,
            (
                SELECT COUNT(*) FROM messages m
                WHERE m.conversation_id = c.id
                  AND m.id > COALESCE(cp.last_read_message_id, 0)
                  AND m.deleted_at IS NULL
                  AND m.author_id IS DISTINCT FROM :user_id
            ) AS unread_count,
            (SELECT m2.content FROM messages m2 WHERE m2.id = c.last_message_id)
                AS last_message_content,
            (SELECT m2.author_id FROM messages m2 WHERE m2.id = c.last_message_id)
                AS last_message_author_id
        FROM conversations c
        JOIN conversation_participants cp
          ON cp.conversation_id = c.id AND cp.user_id = :user_id AND cp.left_at IS NULL
        WHERE c.id = :conv_id
    """)

    params = {"conv_id": conv_id, "user_id": user_id}
    try:
        rows = await session.execute(query_with_jobs, params)
    except ProgrammingError:
        rows = await session.execute(query_without_jobs, params)

    row = rows.first()
    return dict(row._mapping) if row else None


async def get_total_unread(session: AsyncSession, user_id: int) -> int:
    """Calculate total unread messages count across all non-AI conversations."""
    result = await session.execute(
        text("""
            SELECT COALESCE(SUM(unread), 0) FROM (
                SELECT COUNT(*) AS unread
                FROM conversation_participants cp
                JOIN conversations c ON c.id = cp.conversation_id
                JOIN messages m ON m.conversation_id = cp.conversation_id
                WHERE cp.user_id = :user_id
                  AND cp.left_at IS NULL
                  AND c.type != 'ai'
                  AND m.id > COALESCE(cp.last_read_message_id, 0)
                  AND m.deleted_at IS NULL
                  AND m.author_id IS DISTINCT FROM :user_id
                GROUP BY cp.conversation_id
            ) sub
        """),
        {"user_id": user_id},
    )
    return int(result.scalar() or 0)


# ── Participants ──────────────────────────────────────────────────────────────


async def get_participant(
    session: AsyncSession, conv_id: int, user_id: int
) -> ConversationParticipant | None:
    """Get active participant record."""
    q = select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv_id,
        ConversationParticipant.user_id == user_id,
        ConversationParticipant.left_at.is_(None),
    )
    return (await session.execute(q)).scalar_one_or_none()


async def add_participant(
    session: AsyncSession, conv_id: int, user_id: int, role: str = "member"
) -> ConversationParticipant:
    """Add a participant or reactivate a previously left participant."""
    bind = session.bind
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = (
            pg_insert(ConversationParticipant)
            .values(conversation_id=conv_id, user_id=user_id, role=role)
            .on_conflict_do_update(
                index_elements=["conversation_id", "user_id"],
                set_={"left_at": None, "role": role},
            )
            .returning(ConversationParticipant)
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    # Universal fallback for SQLite or unit test dialects
    q = select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv_id,
        ConversationParticipant.user_id == user_id,
    )
    existing = (await session.execute(q)).scalar_one_or_none()
    if existing:
        existing.left_at = None
        existing.role = role
        await session.flush()
        return existing

    p = ConversationParticipant(conversation_id=conv_id, user_id=user_id, role=role)
    session.add(p)
    await session.flush()
    return p


async def remove_participant(session: AsyncSession, conv_id: int, user_id: int) -> None:
    """Soft remove participant by setting left_at timestamp."""
    await session.execute(
        update(ConversationParticipant)
        .where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.user_id == user_id,
        )
        .values(left_at=func.now())
    )


async def list_participants(session: AsyncSession, conv_id: int) -> list[ConversationParticipant]:
    """List active participants of a conversation."""
    q = (
        select(ConversationParticipant)
        .where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.left_at.is_(None),
        )
        .order_by(ConversationParticipant.created_at)
    )
    return list((await session.execute(q)).scalars().all())


async def mark_read(
    session: AsyncSession, conv_id: int, user_id: int, last_message_id: int
) -> None:
    """Advance participant's last_read_message_id pointer."""
    await session.execute(
        update(ConversationParticipant)
        .where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.user_id == user_id,
        )
        .values(last_read_message_id=last_message_id)
    )


# ── Messages ──────────────────────────────────────────────────────────────────


async def get_message(session: AsyncSession, msg_id: int) -> Message | None:
    """Fetch message by ID."""
    return await session.get(Message, msg_id)


async def find_by_idempotency_key(session: AsyncSession, conv_id: int, key: str) -> Message | None:
    """Check for an existing message with the idempotency key in the conversation."""
    q = select(Message).where(
        Message.conversation_id == conv_id,
        Message.idempotency_key == key,
    )
    return (await session.execute(q)).scalar_one_or_none()


async def insert_message(
    session: AsyncSession,
    *,
    conversation_id: int,
    author_id: int | None,
    content: str,
    message_type: str = "text",
    reply_to_id: int | None = None,
    idempotency_key: str | None = None,
) -> Message:
    """Insert a new message into the conversation."""
    msg = Message(
        conversation_id=conversation_id,
        author_id=author_id,
        content=content,
        message_type=message_type,
        reply_to_id=reply_to_id,
        idempotency_key=idempotency_key,
    )
    session.add(msg)
    await session.flush()
    return msg


async def list_messages(
    session: AsyncSession,
    conv_id: int,
    before_id: int | None,
    limit: int,
) -> tuple[list[Message], int | None]:
    """Cursor-paginated message history."""
    q = select(Message).where(
        Message.conversation_id == conv_id,
        Message.deleted_at.is_(None),
    )
    if before_id:
        q = q.where(Message.id < before_id)
    q = q.order_by(Message.id.desc()).limit(limit + 1)
    rows = list((await session.execute(q)).scalars().all())
    items = rows[:limit]
    prev_before = items[-1].id if len(rows) > limit else None
    return list(reversed(items)), prev_before


async def mark_delivered(session: AsyncSession, msg_id: int) -> Message | None:
    """Transition message status from sent to delivered."""
    result = await session.execute(
        update(Message)
        .where(Message.id == msg_id, Message.status == "sent")
        .values(status="delivered")
        .returning(Message)
    )
    return result.scalar_one_or_none()


async def mark_message_read(session: AsyncSession, conv_id: int, up_to_id: int) -> None:
    """Mark all messages up to specified ID as read."""
    await session.execute(
        update(Message)
        .where(
            Message.conversation_id == conv_id,
            Message.id <= up_to_id,
            Message.status != "read",
        )
        .values(status="read")
    )


async def soft_delete_message(session: AsyncSession, msg_id: int) -> None:
    """Mark message deleted_at timestamp without removing row."""
    await session.execute(update(Message).where(Message.id == msg_id).values(deleted_at=func.now()))


async def edit_message(session: AsyncSession, msg_id: int, content: str) -> Message | None:
    """Update message content and set edited_at timestamp."""
    result = await session.execute(
        update(Message)
        .where(Message.id == msg_id, Message.deleted_at.is_(None))
        .values(content=content, edited_at=func.now())
        .returning(Message)
    )
    return result.scalar_one_or_none()


async def get_active_participant_ids(session: AsyncSession, conv_id: int) -> list[int]:
    """Retrieve IDs of all active participants in a conversation."""
    result = await session.execute(
        select(ConversationParticipant.user_id).where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.left_at.is_(None),
        )
    )
    return list(result.scalars().all())
