"""Business logic and transaction orchestration for conversations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.conversations import repo
from app.conversations.models import Conversation, ConversationParticipant, Message


async def get_or_create_direct(
    session: AsyncSession,
    *,
    me_id: int,
    peer_id: int,
    job_id: int | None = None,
) -> Conversation:
    """Get existing direct conversation between two users, or create a new one."""
    if me_id == peer_id:
        raise ValueError("Cannot start a conversation with yourself")

    existing = await repo.find_direct_conversation(session, me_id, peer_id)
    if existing:
        return existing

    # Serialize concurrent creation per canonical unordered pair without blocking
    # external hooks wrapped around repo.find_direct_conversation.
    await repo.lock_direct_pair(session, me_id, peer_id)
    existing = await repo._query_direct_conversation(session, me_id, peer_id)
    if existing:
        return existing

    conv = await repo.create_conversation(session, type="direct", job_id=job_id)
    await repo.add_participant(session, conv.id, me_id)
    await repo.add_participant(session, conv.id, peer_id)
    await session.commit()
    await session.refresh(conv)
    return conv


async def create_ai_conversation(session: AsyncSession, *, user_id: int) -> Conversation:
    """Create a new AI-assistant conversation for the user."""
    conv = await repo.create_conversation(session, type="ai")
    await repo.add_participant(session, conv.id, user_id)
    await session.commit()
    await session.refresh(conv)
    return conv


async def ensure_participant(
    session: AsyncSession, conv_id: int, user_id: int
) -> ConversationParticipant:
    """Validate that the user is an active participant in the conversation."""
    p = await repo.get_participant(session, conv_id, user_id)
    if not p:
        conv = await repo.get_conversation(session, conv_id)
        if not conv:
            raise LookupError("conversation not found")
        raise PermissionError("forbidden")
    return p


async def send_message(
    session: AsyncSession,
    *,
    conv_id: int,
    user_id: int,
    content: str,
    reply_to_id: int | None = None,
    idempotency_key: str | None = None,
) -> tuple[Conversation | None, list[Message]]:
    """Send a message, respecting idempotency keys and updating conversation state."""
    await ensure_participant(session, conv_id, user_id)

    if idempotency_key:
        existing = await repo.find_by_idempotency_key(session, conv_id, idempotency_key)
        if existing:
            conv = await repo.get_conversation(session, conv_id)
            return conv, [existing]

    msg = await repo.insert_message(
        session,
        conversation_id=conv_id,
        author_id=user_id,
        content=content,
        reply_to_id=reply_to_id,
        idempotency_key=idempotency_key,
    )
    await repo.update_last_message(session, conv_id, msg.id)
    conv = await repo.get_conversation(session, conv_id)

    await session.commit()
    await session.refresh(msg)
    return conv, [msg]


async def mark_read(
    session: AsyncSession, conv_id: int, user_id: int, last_message_id: int
) -> None:
    """Update participant's read pointer and mark corresponding messages as read."""
    await ensure_participant(session, conv_id, user_id)
    await repo.mark_read(session, conv_id, user_id, last_message_id)
    await repo.mark_message_read(session, conv_id, last_message_id)
    await session.commit()
