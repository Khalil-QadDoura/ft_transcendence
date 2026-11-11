"""The jobs table: vacancies posted by companies."""

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    Double,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db.base import Base
from app.db.mixins import AuditMixin, TimestampMixin

# draft: only the owner sees it. open: published, accepts applications. deleted: soft delete.
JOB_STATUSES = ("draft", "open", "deleted")
SALARY_TYPES = ("hourly", "daily", "weekly", "monthly")
SCHEDULES = ("full_time", "part_time", "internship")
URGENCIES = ("normal", "urgent", "hot")


class GeographyPoint(UserDefinedType):
    """PostGIS type for a point on the Earth. SQLAlchemy has no built-in name for it."""

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "geography(Point, 4326)"  # 4326 = longitude / latitude in degrees, as GPS


class Job(TimestampMixin, AuditMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        CheckConstraint("salary_amount >= 0", name="salary_not_negative"),
        # Three capital letters, as ISO 4217 codes: AED, EUR, USD.
        CheckConstraint("salary_currency ~ '^[A-Z]{3}$'", name="currency_iso_4217"),
        # GiST: fast "jobs within 10 km". GIN: fast "jobs containing these words".
        Index("ix_jobs_location_point", "location_point", postgresql_using="gist"),
        Index("ix_jobs_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The company that posted the job.
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum(*JOB_STATUSES, name="job_status"), server_default="draft"
    )
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    location: Mapped[str] = mapped_column(String(150))
    salary_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_type: Mapped[str] = mapped_column(
        Enum(*SALARY_TYPES, name="job_salary_type"), server_default="monthly"
    )
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    schedule: Mapped[str] = mapped_column(
        Enum(*SCHEDULES, name="job_schedule"), server_default="full_time"
    )
    urgency: Mapped[str] = mapped_column(
        Enum(*URGENCIES, name="job_urgency"), server_default="normal"
    )
    # Made by PostgreSQL from latitude and longitude, so it can never disagree with them.
    location_point: Mapped[str] = mapped_column(
        GeographyPoint(),
        Computed("ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography"),
    )
    # The words of title and description, kept up to date by a trigger (see the migration).
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
