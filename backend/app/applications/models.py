"""Job applications, the log of their status changes, and job page views."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin

# The allowed moves between them are business rules, checked in code (wozu-backend.md).
APPLICATION_STATUSES = (
    "submitted",
    "viewed",
    "shortlisted",
    "rejected",
    "contacted",
    "hired",
    "withdrawn",
)
# One PostgreSQL type, used by three columns.
application_status = Enum(*APPLICATION_STATUSES, name="application_status")


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    # A person applies to a job once.
    __table_args__ = (UniqueConstraint("job_id", "applicant_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # No separate index: the unique (job_id, applicant_id) above starts with it.
    job_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("jobs.id", ondelete="CASCADE"))
    applicant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The job's company, kept here so "all applications to my company" is one simple query.
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    # The video the applicant had posted; emptied if that video row is ever deleted.
    intro_video_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("intro_videos.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(application_status, server_default="submitted")
    cover_note: Mapped[str | None] = mapped_column(String(1000))
    # The chat with the employer, made when the application moves to "contacted".
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationEvent(TimestampMixin, Base):
    """One row per status change: who moved the application, from what, to what."""

    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Empty for the first event, when the application is submitted.
    from_status: Mapped[str | None] = mapped_column(application_status)
    to_status: Mapped[str] = mapped_column(application_status)
    note: Mapped[str | None] = mapped_column(String(500))


class JobView(TimestampMixin, Base):
    """A counted view of a job page (one per user per 24 hours; the 24 hours live in Redis)."""

    __tablename__ = "job_views"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    # Empty for a visitor who is not logged in.
    viewer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
