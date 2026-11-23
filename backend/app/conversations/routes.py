"""API router for conversations, participants, and messages."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.companies.models import Company
from app.conversations import repo, service
from app.conversations.models import ConversationParticipant
from app.conversations.schemas import (
    AddParticipantRequest,
    ConversationCreate,
    ConversationOut,
    EditMessageRequest,
    MessageOut,
    MessagesPage,
    ParticipantOut,
    PeerOut,
    ReadRequest,
    SendMessageRequest,
    SendResponse,
    UnreadOut,
)
from app.core.redis_client import get_redis
from app.core.storage import Storage, get_storage
from app.db.session import get_session
from app.users.constants import DELETED_USER_NAME

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _msg_out(m: Any) -> MessageOut:
    return MessageOut.model_validate(m)


def _conv_out(row: dict[str, Any], storage: Storage | None = None) -> ConversationOut:
    peer: PeerOut | None = None
    peer_id = row.get("peer_id")
    if peer_id is not None:
        if storage is None:
            from app.core.config import settings

            storage = Storage(settings=settings)
        first_name = row.get("peer_first_name")
        last_name = row.get("peer_last_name")
        avatar_key = row.get("peer_avatar_key")
        parts = [p for p in (first_name, last_name) if p]
        display_name = " ".join(parts) if parts else f"User {peer_id}"
        if row.get("peer_status") == "deleted":
            # A deleted account shows no profile, from its deletion on and once anonymised
            # (BE-34): "Deleted user", no name, the default picture. Its messages stay.
            first_name = last_name = avatar_key = None
            display_name = DELETED_USER_NAME
        peer = PeerOut(
            id=peer_id,
            first_name=first_name,
            last_name=last_name,
            display_name=display_name,
            avatar_url=storage.avatar_url(avatar_key),
        )
    return ConversationOut(
        id=row["id"],
        type=row["type"],
        title=row.get("title"),
        job_id=row.get("job_id"),
        job_title=row.get("job_title"),
        last_message_id=row.get("last_message_id"),
        last_message_content=row.get("last_message_content"),
        last_message_author_id=row.get("last_message_author_id"),
        unread_count=row.get("unread_count", 0),
        updated_at=row["updated_at"],
        peer=peer,
    )


async def _require_participant(
    session: AsyncSession, conv_id: int, user_id: int
) -> ConversationParticipant:
    p = await repo.get_participant(session, conv_id, user_id)
    if not p:
        conv = await repo.get_conversation(session, conv_id)
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="conversation not found",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden",
        )
    return p


async def _validate_job_owner(session: AsyncSession, job_id: int, user_id: int) -> None:
    """Ensure the job belongs to an active company owned by the user.

    Accepts 'draft' and 'open' job status.
    """
    from app.jobs.models import Job

    result = await session.execute(
        select(Job.id)
        .join(Company, Company.id == Job.owner_id)
        .where(
            Job.id == job_id,
            Job.status.in_(["draft", "open"]),
            Company.owner_user_id == user_id,
            Company.status == "active",
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="job_id does not belong to your company or is not active",
        )


# ── Conversations ─────────────────────────────────────────────────────────────


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    me: CurrentUser,
) -> ConversationOut:
    """Create or retrieve a direct conversation, or create an AI conversation."""
    if body.job_id is not None:
        await _validate_job_owner(session, job_id=body.job_id, user_id=me.id)

    if body.type == "direct":
        if not body.peer_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="peer_user_id is required for direct conversations",
            )
        try:
            conv = await service.get_or_create_direct(
                session, me_id=me.id, peer_id=body.peer_user_id, job_id=body.job_id
            )
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            ) from None
    else:
        conv = await service.create_ai_conversation(session, user_id=me.id)

    row = await repo.get_conversation_for_user(session, conv.id, me.id)
    if row:
        return _conv_out(row, storage)

    return ConversationOut(
        id=conv.id,
        type=conv.type,
        title=conv.title,
        job_id=conv.job_id,
        job_title=None,
        last_message_id=None,
        last_message_content=None,
        last_message_author_id=None,
        unread_count=0,
        updated_at=conv.updated_at,
        peer=None,
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    me: CurrentUser,
    limit: int = Query(50, ge=1, le=100),
) -> list[ConversationOut]:
    """List conversations for the current user ordered by updated_at descending."""
    rows = await repo.list_conversations_for_user(session, me.id, limit)
    return [_conv_out(r, storage) for r in rows]


@router.get("/unread", response_model=UnreadOut)
async def get_unread(
    session: Annotated[AsyncSession, Depends(get_session)],
    me: CurrentUser,
) -> UnreadOut:
    """Get total unread messages count across all non-AI conversations."""
    return UnreadOut(total_unread=await repo.get_total_unread(session, me.id))


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    me: CurrentUser,
) -> ConversationOut:
    """Get conversation details with unread count for current user."""
    row = await repo.get_conversation_for_user(session, conv_id, me.id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found or forbidden",
        )
    return _conv_out(row, storage)


@router.delete("/{conv_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_conversation(
    conv_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: CurrentUser,
) -> None:
    """Leave a conversation."""
    await _require_participant(session, conv_id, me.id)
    await repo.remove_participant(session, conv_id, me.id)
    await session.commit()


# ── Participants ──────────────────────────────────────────────────────────────


@router.get("/{conv_id}/participants", response_model=list[ParticipantOut])
async def list_participants(
    conv_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: CurrentUser,
) -> list[ParticipantOut]:
    """List active participants of a conversation."""
    await _require_participant(session, conv_id, me.id)
    participants = await repo.list_participants(session, conv_id)
    return [ParticipantOut.model_validate(p) for p in participants]


@router.post("/{conv_id}/participants", status_code=status.HTTP_201_CREATED)
async def add_participant(
    conv_id: int,
    body: AddParticipantRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: CurrentUser,
) -> dict[str, bool]:
    """Add a participant to the conversation (admin only)."""
    p = await _require_participant(session, conv_id, me.id)
    if p.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admins can add participants",
        )
    await repo.add_participant(session, conv_id, body.user_id, body.role)
    await session.commit()
    return {"added": True}


@router.delete("/{conv_id}/participants/{uid}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_participant(
    conv_id: int,
    uid: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: CurrentUser,
) -> None:
    """Remove a participant from the conversation (admin or self)."""
    p = await _require_participant(session, conv_id, me.id)
    if uid != me.id and p.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admins can remove other participants",
        )
    await repo.remove_participant(session, conv_id, uid)
    await session.commit()


# ── Messages ──────────────────────────────────────────────────────────────────


@router.get("/{conv_id}/messages", response_model=MessagesPage)
async def list_messages(
    conv_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: CurrentUser,
    before_id: int | None = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> MessagesPage:
    """List messages with cursor pagination."""
    await _require_participant(session, conv_id, me.id)
    items, prev = await repo.list_messages(session, conv_id, before_id, limit)
    return MessagesPage(items=[_msg_out(m) for m in items], prev_before_id=prev)


@router.post("/{conv_id}/messages", response_model=SendResponse)
async def send_message(
    conv_id: int,
    body: SendMessageRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    me: CurrentUser,
) -> SendResponse:
    """Send a message and broadcast over BE-06 WebSockets when newly created."""
    try:
        items = await service.send_message_and_broadcast(
            session,
            redis,
            conv_id=conv_id,
            user_id=me.id,
            content=body.content,
            reply_to_id=body.reply_to_id,
            idempotency_key=body.idempotency_key,
        )
    except LookupError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from None
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden") from None

    return SendResponse(items=items)


@router.patch("/{conv_id}/messages/{mid}", response_model=MessageOut)
async def edit_message(
    conv_id: int,
    mid: int,
    body: EditMessageRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    me: CurrentUser,
) -> MessageOut:
    """Edit own message within the 15-minute window and broadcast message_updated."""
    try:
        updated = await service.edit_message(
            session, conv_id=conv_id, msg_id=mid, user_id=me.id, content=body.content
        )
    except LookupError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from None
    except PermissionError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from None
    except service.EditWindowExpiredError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err)) from None

    out = _msg_out(updated)
    await service.broadcast_event(session, redis, conv_id, "message_updated", out)
    return out


@router.delete("/{conv_id}/messages/{mid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    conv_id: int,
    mid: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    me: CurrentUser,
) -> None:
    """Soft delete own message and broadcast message_deleted."""
    try:
        await service.delete_message(session, conv_id=conv_id, msg_id=mid, user_id=me.id)
    except LookupError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from None
    except PermissionError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from None

    await service.broadcast_event(
        session, redis, conv_id, "message_deleted", {"id": mid, "conversation_id": conv_id}
    )


@router.post("/{conv_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    conv_id: int,
    body: ReadRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    me: CurrentUser,
) -> None:
    """Mark conversation messages as read up to the given message ID."""
    try:
        await service.mark_read_and_broadcast(
            session,
            redis,
            conv_id=conv_id,
            user_id=me.id,
            last_message_id=body.last_message_id,
        )
    except LookupError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from None
    except PermissionError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from None
