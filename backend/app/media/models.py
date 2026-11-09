"""The intro_videos table: the 30-second video CVs of job seekers."""

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin

# Set by the moderation worker. moderation_error: the check itself failed (download, ffmpeg).
MODERATION_STATUSES = ("pending", "approved", "rejected", "moderation_error")
# loaded: uploaded, not shown. posted: shown in the feed. unposted: hidden again.
LIFECYCLE_STATUSES = ("loaded", "posted", "unposted", "deleted")
# A quality grade: the employers' feed shows only A and B.
VIDEO_RATINGS = ("A", "B", "C")


class IntroVideo(TimestampMixin, Base):
    __tablename__ = "intro_videos"
    __table_args__ = (
        # A user shows one video at a time: only one of their videos can be "posted".
        Index(
            "uq_intro_videos_user_id_posted",
            "user_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'posted'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Where the file is in storage (MinIO), for example "users/12/intro/<uuid>.mp4".
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    duration_sec: Mapped[int]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(100))
    moderation_status: Mapped[str] = mapped_column(
        Enum(*MODERATION_STATUSES, name="moderation_status"), server_default="pending"
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    lifecycle_status: Mapped[str] = mapped_column(
        Enum(*LIFECYCLE_STATUSES, name="lifecycle_status"), server_default="loaded"
    )
    video_rating: Mapped[str] = mapped_column(
        Enum(*VIDEO_RATINGS, name="video_rating"), server_default="B"
    )
