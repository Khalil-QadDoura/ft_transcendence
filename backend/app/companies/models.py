"""The companies table: the employer side of the app."""

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin, TimestampMixin

COMPANY_STATUSES = ("active", "deleted")


class Company(TimestampMixin, AuditMixin, Base):
    """A user who owns an active company is an employer and can post jobs."""

    __tablename__ = "companies"
    __table_args__ = (
        # One active company per owner; deleted companies do not count.
        Index(
            "uq_companies_owner_active",
            "owner_user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    logo_object_key: Mapped[str | None] = mapped_column(String(500))
    # Soft delete, like users.
    status: Mapped[str] = mapped_column(
        Enum(*COMPANY_STATUSES, name="company_status"), server_default="active"
    )
    country: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2))
