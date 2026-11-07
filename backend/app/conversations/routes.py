"""API router for conversations, participants, and messages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, get_current_user
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
    ReadRequest,
    SendMessageRequest,
    SendResponse,
    UnreadOut,
)
from app.db.session import get_session
from app.realtime.connection_manager import manager

router = APIRouter(prefix="/conversations", tags=["conversations"])

_EDIT_WINDOW = timedelta(minutes=15)


def _msg_out(m: Any) -> MessageOut:
    return MessageOut.model_validate(m)


def _conv_out(row: dict[str, Any]) -> ConversationOut:
    return ConversationOut(**row)


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

    Accepts both 'active' and 'open' job status.
    """
    try:
        from app.jobs.models import Job

        result = await session.execute(
            select(Job.id)
            .join(Company, Company.id == Job.owner_id)
            .where(
                Job.id == job_id,
                Job.status.in_(["active", "open"]),
                Company.owner_user_id == user_id,
                Company.status == "active",
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="job_id does not belong to your company or is not active",
            )
    except ImportError:
        pass


# ── Conversations ─────────────────────────────────────────────────────────────


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: Annotated[CurrentUser, Depends(get_current_user)],
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
        return _conv_out(row)

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
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    session: Annotated[AsyncSession, Depends(get_session)],
    me: Annotated[CurrentUser, Depends(get_current_user)],
    limit: int = Query(50, ge=1, le=100),
) -> list[ConversationOut]:
    """List conversations for the current user ordered by updated_at descending."""
    rows = await repo.list_conversations_for_user(session, me.id, limit)
    return [_conv_out(r) for r in rows]


@router.get("/unread", response_model=UnreadOut)
async def get_unread(
    session: Annotated[AsyncSession, Depends(get_session)],
    me: Annotated[CurrentUser, Depends(get_current_user)],
) -> UnreadOut:
    """Get total unread messages count across all non-AI conversations."""
    return UnreadOut(total_unread=await repo.get_total_unread(session, me.id))


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: Annotated[CurrentUser, Depends(get_current_user)],
) -> ConversationOut:
    """Get conversation details with unread count for current user."""
    row = await repo.get_conversation_for_user(session, conv_id, me.id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found or forbidden",
        )
    return _conv_out(row)


@router.delete("/{conv_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_conversation(
    conv_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: Annotated[CurrentUser, Depends(get_current_user)],
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
    me: Annotated[CurrentUser, Depends(get_current_user)],
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
    me: Annotated[CurrentUser, Depends(get_current_user)],
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
    me: Annotated[CurrentUser, Depends(get_current_user)],
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
    me: Annotated[CurrentUser, Depends(get_current_user)],
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
    me: Annotated[CurrentUser, Depends(get_current_user)],
) -> SendResponse:
    """Send a message and broadcast over WebSocket."""
    try:
        conv, msgs = await service.send_message(
            session,
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

    participant_ids = await repo.get_active_participant_ids(session, conv_id)
    for msg in msgs:
        payload = {"type": "message", "payload": _msg_out(msg).model_dump(mode="json")}
        for uid in participant_ids:
            await manager.send_to_user(uid, payload)

    return SendResponse(items=[_msg_out(m) for m in msgs])


@router.patch("/{conv_id}/messages/{mid}", response_model=MessageOut)
async def edit_message(
    conv_id: int,
    mid: int,
    body: EditMessageRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: Annotated[CurrentUser, Depends(get_current_user)],
) -> MessageOut:
    """Edit own message within the 15-minute window."""
    await _require_participant(session, conv_id, me.id)
    msg = await repo.get_message(session, mid)
    if not msg or msg.conversation_id != conv_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")
    if msg.author_id != me.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot edit another user's message",
        )
    created_tz = (
        msg.created_at if msg.created_at.tzinfo is not None else msg.created_at.replace(tzinfo=UTC)
    )
    if datetime.now(UTC) - created_tz > _EDIT_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="edit window expired (15 minutes)",
        )

    updated = await repo.edit_message(session, mid, body.content)
    await session.commit()
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")

    # Broadcast message_updated event
    participant_ids = await repo.get_active_participant_ids(session, conv_id)
    payload = {"type": "message_updated", "payload": _msg_out(updated).model_dump(mode="json")}
    for uid in participant_ids:
        await manager.send_to_user(uid, payload)

    return _msg_out(updated)


@router.delete("/{conv_id}/messages/{mid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    conv_id: int,
    mid: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Soft delete own message."""
    await _require_participant(session, conv_id, me.id)
    msg = await repo.get_message(session, mid)
    if not msg or msg.conversation_id != conv_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")
    if msg.author_id != me.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot delete another user's message",
        )
    await repo.soft_delete_message(session, mid)
    await session.commit()

    # Broadcast message_deleted event
    participant_ids = await repo.get_active_participant_ids(session, conv_id)
    payload = {"type": "message_deleted", "payload": {"id": mid, "conversation_id": conv_id}}
    for uid in participant_ids:
        await manager.send_to_user(uid, payload)


@router.post("/{conv_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    conv_id: int,
    body: ReadRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    me: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Mark conversation messages as read up to the given message ID."""
    try:
        await service.mark_read(session, conv_id, me.id, body.last_message_id)
    except (LookupError, PermissionError) as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from None

    participant_ids = await repo.get_active_participant_ids(session, conv_id)
    unread = await repo.get_total_unread(session, me.id)
    for uid in participant_ids:
        await manager.send_to_user(
            uid,
            {
                "type": "conversation_updated",
                "payload": {
                    "conversation_id": conv_id,
                    "unread_count": unread if uid == me.id else None,
                },
            },
        )
