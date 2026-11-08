"""Friend requests and friendships: one row per pair of users."""

from sqlalchemy import BigInteger, CheckConstraint, Enum, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin

FRIENDSHIP_STATUSES = ("pending", "accepted", "declined")


class Friendship(TimestampMixin, Base):
    """A request from requester to addressee; once accepted, the two are friends."""

    __tablename__ = "friendships"
    __table_args__ = (
        CheckConstraint("requester_id <> addressee_id", name="not_self"),
        # One live row per pair, whoever asked first: (1, 2) and (2, 1) are the same pair.
        # Declined rows do not count, so the pair can try again later.
        Index(
            "uq_friendships_pair",
            text("least(requester_id, addressee_id)"),
            text("greatest(requester_id, addressee_id)"),
            unique=True,
            postgresql_where=text("status IN ('pending', 'accepted')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requester_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    addressee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        Enum(*FRIENDSHIP_STATUSES, name="friendship_status"), server_default="pending"
    )
