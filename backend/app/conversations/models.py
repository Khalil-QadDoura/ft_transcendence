"""Chats: conversations, who is in them, and their messages."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin

CONVERSATION_TYPES = ("direct", "group", "ai")
PARTICIPANT_ROLES = ("member", "admin", "bot")
MESSAGE_STATUSES = ("sent", "delivered", "read")
MESSAGE_TYPES = ("text", "system", "ai")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(Enum(*CONVERSATION_TYPES, name="conversation_type"))
    title: Mapped[str | None] = mapped_column(String(150))
    # Set when the chat is about a job.
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    # A copy of the newest message's id, so the chat list needs no extra query. Not a
    # foreign key, on purpose (wozu-backend.md): it is a shortcut, not a relation.
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)


class ConversationParticipant(TimestampMixin, Base):
    """One row per user in a conversation."""

    __tablename__ = "conversation_participants"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # No separate index: the unique (conversation_id, user_id) above starts with it.
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(
        Enum(*PARTICIPANT_ROLES, name="participant_role"), server_default="member"
    )
    # The last message this user has read (unread = the messages after it). A shortcut too.
    last_read_message_id: Mapped[int | None] = mapped_column(BigInteger)
    is_muted: Mapped[bool] = mapped_column(server_default=false())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        # The same send retried with the same idempotency_key creates one message, not two.
        # Messages without a key never clash: in SQL, two empty (NULL) values are not equal.
        UniqueConstraint("conversation_id", "idempotency_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # Empty if the author's account is ever deleted; the message itself stays.
    author_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum(*MESSAGE_STATUSES, name="message_status"), server_default="sent"
    )
    reply_to_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    message_type: Mapped[str] = mapped_column(
        Enum(*MESSAGE_TYPES, name="message_type"), server_default="text"
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Soft delete: the row stays, the app shows "message deleted".
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
