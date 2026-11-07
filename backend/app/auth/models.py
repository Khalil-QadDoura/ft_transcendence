"""Login sessions (refresh tokens) and password reset tokens."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class RefreshToken(TimestampMixin, Base):
    """One row per refresh token given out at login or refresh."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The token's unique id (its "jti" claim). The token itself is not stored.
    jti: Mapped[str] = mapped_column(String(64), unique=True)
    # The user's token_version when the token was made; a lower number means "revoked".
    token_version: Mapped[int]
    # Indexed because old tokens are deleted by expiry date.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(server_default=false())


class PasswordResetToken(TimestampMixin, Base):
    """A "forgot password" link: valid for a short time and only once."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set when the link is used, so it cannot be used again.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
