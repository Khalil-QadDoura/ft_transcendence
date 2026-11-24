"""Database queries of sign-up, login and passwords: users, their refresh tokens and their
password reset tokens. No HTTP, no rules."""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetToken, RefreshToken
from app.users.models import User


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def create_or_update_unverified_user(
    session: AsyncSession, email: str, password_hash: str
) -> User | None:
    """Create the account, or give a not yet verified one the new password, as one database
    step ("insert, or if the email is taken, update"). Replacing the password raises
    token_version, which makes the older verification links useless.

    Returns None, and changes nothing, when the email is already verified. PostgreSQL locks
    the row while it checks, so a link opened at the same moment cannot verify the account
    in between the check and the change.
    """
    new_user = insert(User).values(email=email, password_hash=password_hash)
    return await session.scalar(
        new_user.on_conflict_do_update(
            index_elements=[User.email],
            set_={
                "password_hash": new_user.excluded.password_hash,  # the password just sent
                "token_version": User.token_version + 1,
                "updated_at": func.now(),  # not filled in automatically for this kind of update
            },
            where=User.is_email_verified.is_(False),
        ).returning(User)
    )


async def mark_email_verified(
    session: AsyncSession, user_id: int, token_version: int | None
) -> User | None:
    """Verify the email, as one database step, only if the link is the newest one: its
    token_version must still be the user's. Returns None, and changes nothing, when the link
    is too old, the email is already verified or the account is deleted."""
    return await session.scalar(
        update(User)
        .where(
            User.id == user_id,
            User.token_version == token_version,
            User.is_email_verified.is_(False),
            User.status == "active",
        )
        .values(is_email_verified=True)
        .returning(User)
    )


def add_refresh_token(
    session: AsyncSession, user_id: int, jti: str, token_version: int, expires_at: datetime
) -> None:
    """Remember a refresh token by its id (jti), saved with the next commit."""
    session.add(
        RefreshToken(user_id=user_id, jti=jti, token_version=token_version, expires_at=expires_at)
    )


async def revoke_refresh_token(session: AsyncSession, jti: str) -> RefreshToken | None:
    """Mark the token revoked and return its row, as one database step. Returns None when it
    is unknown or was already revoked, so if the same token comes twice, only one call wins."""
    return await session.scalar(
        update(RefreshToken)
        .where(RefreshToken.jti == jti, RefreshToken.revoked.is_(False))
        .values(revoked=True)
        .returning(RefreshToken)
    )


async def set_password(session: AsyncSession, user_id: int, password_hash: str) -> User | None:
    """Store the new password and raise token_version by 1, as one database step. Every token
    made before (access and refresh, on every device) carries the old version and stops
    working. Returns None, and changes nothing, when the account is deleted."""
    return await session.scalar(
        update(User)
        .where(User.id == user_id, User.status == "active")
        .values(password_hash=password_hash, token_version=User.token_version + 1)
        .returning(User)
    )


def add_password_reset_token(
    session: AsyncSession, user_id: int, token_hash: str, expires_at: datetime
) -> None:
    """Remember a reset link, saved with the next commit. The `token` column gets the token's
    hash (security.hash_reset_token), never the token itself."""
    session.add(PasswordResetToken(user_id=user_id, token=token_hash, expires_at=expires_at))


async def use_password_reset_token(
    session: AsyncSession, token_hash: str
) -> PasswordResetToken | None:
    """Mark the reset link used and return its row, as one database step, only if it is
    known, not used yet and not expired. Returns None otherwise: if the same link comes
    twice, even at the same moment, only one call wins."""
    return await session.scalar(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > func.now(),
        )
        .values(used_at=func.now())
        .returning(PasswordResetToken)
    )


async def close_password_reset_tokens(session: AsyncSession, user_id: int) -> None:
    """Mark every reset link of the user that still works as used, so an older email cannot
    change the password again after a change or a reset."""
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=func.now())
    )


async def get_or_create_42_user(
    session: AsyncSession, email: str, first_name: str | None, last_name: str | None
) -> User:
    """The account with this email, for a login with 42 (BE-11), locked until the commit. If
    there is none, it is created first: already verified (42 checked the email) and with no
    password. Two logins with 42 for the same new email at the same moment: one creates the
    account, the other waits for it and then finds it, so there is never a second account."""
    user = await _lock_user_by_email(session, email)
    if user is None:
        await session.execute(
            insert(User)
            .values(email=email, is_email_verified=True, first_name=first_name, last_name=last_name)
            .on_conflict_do_nothing(index_elements=[User.email])
        )
        user = await _lock_user_by_email(session, email)
    return user


async def _lock_user_by_email(session: AsyncSession, email: str) -> User | None:
    """SELECT ... FOR UPDATE: the row stays locked until the commit or rollback, so a sign-up,
    a verification link or a deletion at the same moment waits for us."""
    return await session.scalar(select(User).where(User.email == email).with_for_update())


async def verify_and_remove_password(session: AsyncSession, user_id: int) -> User:
    """A login with 42 into an account that was never verified (BE-11): mark the email
    verified, remove the password and raise token_version, as one database step. The
    password was chosen by whoever signed up with this email, and that may not be its owner."""
    return await session.scalar(
        update(User)
        .where(User.id == user_id)
        .values(is_email_verified=True, password_hash=None, token_version=User.token_version + 1)
        .returning(User)
    )
