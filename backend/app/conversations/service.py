"""Business logic for conversations, participants, messages, and live broadcasts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversations import repo
from app.conversations.models import Conversation, ConversationParticipant, Message
from app.conversations.schemas import MessageOut

EDIT_WINDOW = timedelta(minutes=15)


class EditWindowExpiredError(Exception):
    """Raised when attempting to edit a message older than the edit window."""


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


async def broadcast_event(
    session: AsyncSession,
    redis: Redis,
    conv_id: int,
    event_type: str,
    payload: Any,
) -> None:
    """Push one realtime event via BE-06 to every active conversation participant."""
    from app.realtime.service import send_to_user

    for uid in await repo.get_active_participant_ids(session, conv_id):
        await send_to_user(redis, uid, event_type, payload)


async def send_message(
    session: AsyncSession,
    *,
    conv_id: int,
    user_id: int,
    content: str,
    reply_to_id: int | None = None,
    idempotency_key: str | None = None,
) -> tuple[Conversation | None, list[Message], bool]:
    """Send a message idempotently; returns (conversation, [message], created)."""
    await ensure_participant(session, conv_id, user_id)
    normalized_key = idempotency_key or None

    if normalized_key:
        existing = await repo.find_by_idempotency_key(session, conv_id, normalized_key)
        if existing:
            conv = await repo.get_conversation(session, conv_id)
            return conv, [existing], False

    if reply_to_id is not None:
        reply_target = await repo.get_message(session, reply_to_id)
        if (
            not reply_target
            or reply_target.conversation_id != conv_id
            or reply_target.deleted_at is not None
        ):
            raise LookupError("reply target message not found")

    try:
        msg = await repo.insert_message(
            session,
            conversation_id=conv_id,
            author_id=user_id,
            content=content,
            reply_to_id=reply_to_id,
            idempotency_key=normalized_key,
        )
        await repo.update_last_message(session, conv_id, msg.id)
        conv = await repo.get_conversation(session, conv_id)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if normalized_key:
            existing = await repo.find_by_idempotency_key(session, conv_id, normalized_key)
            if existing:
                conv = await repo.get_conversation(session, conv_id)
                return conv, [existing], False
        raise

    await session.refresh(msg)
    return conv, [msg], True


async def send_message_and_broadcast(
    session: AsyncSession,
    redis: Redis,
    *,
    conv_id: int,
    user_id: int,
    content: str,
    reply_to_id: int | None = None,
    idempotency_key: str | None = None,
) -> list[MessageOut]:
    """Send a message and broadcast over BE-06 WebSockets only when newly created."""
    _, msgs, created = await send_message(
        session,
        conv_id=conv_id,
        user_id=user_id,
        content=content,
        reply_to_id=reply_to_id,
        idempotency_key=idempotency_key,
    )
    items = [MessageOut.model_validate(m) for m in msgs]
    if created:
        for item in items:
            await broadcast_event(session, redis, conv_id, "message", item)
    return items


async def edit_message(
    session: AsyncSession,
    *,
    conv_id: int,
    msg_id: int,
    user_id: int,
    content: str,
) -> Message:
    """Edit the caller's own non-deleted message within the 15-minute window."""
    await ensure_participant(session, conv_id, user_id)
    msg = await repo.get_message(session, msg_id)
    if not msg or msg.conversation_id != conv_id or msg.deleted_at is not None:
        raise LookupError("message not found")
    if msg.author_id != user_id:
        raise PermissionError("cannot edit another user's message")

    created_tz = (
        msg.created_at if msg.created_at.tzinfo is not None else msg.created_at.replace(tzinfo=UTC)
    )
    if datetime.now(UTC) - created_tz > EDIT_WINDOW:
        raise EditWindowExpiredError("edit window expired (15 minutes)")

    updated = await repo.edit_message(session, msg_id, content)
    if not updated:
        await session.rollback()
        raise LookupError("message not found")
    await session.commit()
    return updated


async def delete_message(
    session: AsyncSession,
    *,
    conv_id: int,
    msg_id: int,
    user_id: int,
) -> None:
    """Soft-delete the caller's own non-deleted message."""
    await ensure_participant(session, conv_id, user_id)
    msg = await repo.get_message(session, msg_id)
    if not msg or msg.conversation_id != conv_id or msg.deleted_at is not None:
        raise LookupError("message not found")
    if msg.author_id != user_id:
        raise PermissionError("cannot delete another user's message")

    deleted = await repo.soft_delete_message(session, msg_id)
    if not deleted:
        await session.rollback()
        raise LookupError("message not found")
    await session.commit()


async def mark_read(
    session: AsyncSession, conv_id: int, user_id: int, last_message_id: int
) -> None:
    """Update participant's read pointer and mark corresponding peer messages as read."""
    await ensure_participant(session, conv_id, user_id)
    await repo.mark_read(session, conv_id, user_id, last_message_id)
    await repo.mark_message_read(session, conv_id, last_message_id, viewer_id=user_id)
    await session.commit()


async def mark_read_and_broadcast(
    session: AsyncSession,
    redis: Redis,
    *,
    conv_id: int,
    user_id: int,
    last_message_id: int,
) -> None:
    """Advance read state and push conversation_updated to active participants."""
    from app.realtime.service import send_to_user

    await mark_read(session, conv_id, user_id, last_message_id)
    participant_ids = await repo.get_active_participant_ids(session, conv_id)
    unread = await repo.get_total_unread(session, user_id)
    for uid in participant_ids:
        await send_to_user(
            redis,
            uid,
            "conversation_updated",
            {
                "conversation_id": conv_id,
                "unread_count": unread if uid == user_id else None,
            },
        )


async def mark_delivered_and_broadcast(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: int,
    message_id: int,
) -> None:
    """Mark a message as delivered for a non-author participant and push message_status."""
    msg = await repo.get_message(session, message_id)
    if not msg or msg.deleted_at is not None:
        return
    participant = await repo.get_participant(session, msg.conversation_id, user_id)
    if participant is None:
        return

    updated = await repo.mark_delivered(session, message_id, viewer_id=user_id)
    if updated is None:
        await session.rollback()
        return
    await session.commit()
    await broadcast_event(
        session,
        redis,
        msg.conversation_id,
        "message_status",
        {"message_id": message_id, "status": "delivered"},
    )
