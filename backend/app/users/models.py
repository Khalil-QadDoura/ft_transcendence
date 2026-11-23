"""The users table: one row per account."""

from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, Enum, String, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin

USER_STATUSES = ("active", "deleted")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # Empty for an account that only signs in with 42 (OAuth).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_email_verified: Mapped[bool] = mapped_column(server_default=false())
    first_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str | None] = mapped_column(String(50))
    position: Mapped[str | None] = mapped_column(String(100))
    birth_date: Mapped[date | None]
    bio: Mapped[str | None] = mapped_column(String(500))
    avatar_object_key: Mapped[str | None] = mapped_column(String(500))
    # Goes up by 1 on a password change or reset, which makes every older token invalid.
    token_version: Mapped[int] = mapped_column(server_default=text("1"))
    # Soft delete: an account is never removed, only marked "deleted".
    status: Mapped[str] = mapped_column(
        Enum(*USER_STATUSES, name="user_status"), server_default="active"
    )
    # When DELETE /api/users/me deleted the account (BE-34); empty while it is active. The
    # daily job of the worker anonymises the account 30 days later (users/anonymise.py).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by hand by the team while a complaint or dispute about the account is open: the
    # daily job skips the account until it is false again (backend/README.md says how).
    retention_hold: Mapped[bool] = mapped_column(server_default=false())
    # When the daily job anonymised the account; it never picks the account again.
    anonymised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
