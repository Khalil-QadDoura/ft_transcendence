"""The users table: one row per account."""

from datetime import date

from sqlalchemy import BigInteger, Enum, String, false, text
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
