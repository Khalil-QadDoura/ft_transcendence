"""The rules of sign-up and login. Routes call these functions; these call the repo."""

import asyncio

import jwt
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import repo, security
from app.auth.constants import (
    ACCESS_SCOPE,
    ACCESS_TOKEN_LIFETIME,
    EMAIL_VERIFY_SCOPE,
    EMAIL_VERIFY_TOKEN_LIFETIME,
    REFRESH_SCOPE,
    REFRESH_TOKEN_LIFETIME,
)
from app.auth.schemas import LoginIn, RegisterIn, TokenPairOut, VerifyOut
from app.core.config import Settings
from app.core.mailer import Mailer
from app.users.models import User

EMAIL_TAKEN = "Email already registered"
INVALID_LINK = "Invalid or expired link"
INVALID_CREDENTIALS = "Invalid email or password"
EMAIL_NOT_VERIFIED = "Email not verified"
INVALID_TOKEN = "Invalid or expired token"

VERIFY_SUBJECT = "Verify your WOZU account"
VERIFY_BODY = """\
Welcome to WOZU!

Open this link to verify your email address:
{link}

If you did not sign up, you can ignore this email.
"""


async def register(
    session: AsyncSession,
    settings: Settings,
    mailer: Mailer,
    background: BackgroundTasks,
    data: RegisterIn,
) -> None:
    """Create the account, or update one that is not verified yet, and email the link."""
    # Argon2 is slow on purpose, so it runs in a worker thread: meanwhile the server keeps
    # answering other requests.
    password_hash = await asyncio.to_thread(security.hash_password, data.password)
    # Signing up again before verifying keeps the one account, with the newest password and
    # a raised token_version. Check and change are one database step (see the repo).
    user = await repo.create_or_update_unverified_user(session, data.email, password_hash)
    if user is None:  # already verified: that account is never changed here
        raise HTTPException(status_code=409, detail=EMAIL_TAKEN)
    await session.commit()

    # "ver" ties the link to this password: a new sign-up raises token_version, and from then
    # on only its link (the newest one) works.
    token, _ = security.create_token(
        settings.jwt_secret,
        user.id,
        EMAIL_VERIFY_SCOPE,
        EMAIL_VERIFY_TOKEN_LIFETIME,
        ver=user.token_version,
    )
    # The link opens the frontend's page, which calls GET /api/auth/verify with the token.
    link = f"{settings.frontend_base_url.rstrip('/')}/verify-email?token={token}"
    # Sent after the answer has gone out (202 Accepted: the work is not finished yet).
    background.add_task(mailer.send, user.email, VERIFY_SUBJECT, VERIFY_BODY.format(link=link))


async def verify_email(session: AsyncSession, settings: Settings, token: str) -> VerifyOut:
    """Mark the email of the token's user as verified, if this is the newest link.
    Opening it twice is fine."""
    try:
        claims = security.read_token(settings.jwt_secret, token, EMAIL_VERIFY_SCOPE)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail=INVALID_LINK) from None
    user_id, version = int(claims["sub"]), claims.get("ver")
    # The check (is this still the newest link?) and the change are one database step, so a
    # sign-up at the same moment cannot slip a new password in between.
    user = await repo.mark_email_verified(session, user_id, version)
    await session.commit()
    if user is not None:
        return VerifyOut(verified=True, email=user.email, updated=True)
    # Nothing changed. Fine if this newest link was already used: a verified account never
    # goes back to unverified, and sign-up never changes it, so this answer cannot go stale.
    user = await repo.get_user_by_id(session, user_id)
    if (
        user is None
        or user.status != "active"
        or not user.is_email_verified
        or user.token_version != version
    ):
        raise HTTPException(status_code=400, detail=INVALID_LINK)
    return VerifyOut(verified=True, email=user.email, updated=False)


async def login(session: AsyncSession, settings: Settings, data: LoginIn) -> TokenPairOut:
    """Check the email and password; give a new access and refresh token pair."""
    user = await repo.get_user_by_email(session, data.email)
    # No account (or a deleted one) and a wrong password get the same answer, so nobody can
    # use login to find out which emails have an account.
    password_hash = user.password_hash if user is not None and user.status == "active" else None
    if not await asyncio.to_thread(security.verify_password, data.password, password_hash):
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)
    # Checked after the password, so only the owner learns that the email is not verified.
    if not user.is_email_verified:
        raise HTTPException(status_code=403, detail=EMAIL_NOT_VERIFIED)
    return await issue_token_pair(session, settings, user)


async def refresh(session: AsyncSession, settings: Settings, refresh_token: str) -> TokenPairOut:
    """Rotation: the refresh token is used up (revoked) and a new pair is given."""
    try:
        claims = security.read_token(settings.jwt_secret, refresh_token, REFRESH_SCOPE)
    except jwt.InvalidTokenError:  # changed, expired, or not a refresh token
        raise HTTPException(status_code=401, detail=INVALID_TOKEN) from None
    row = await repo.revoke_refresh_token(session, claims["jti"])
    if row is None:  # already used once, or logged out: a reused token gets nothing
        raise HTTPException(status_code=401, detail=INVALID_TOKEN)
    user = await repo.get_user_by_id(session, row.user_id)
    # token_version goes up when the password changes (BE-04): older tokens stop working.
    if user.status != "active" or row.token_version != user.token_version:
        raise HTTPException(status_code=401, detail=INVALID_TOKEN)
    return await issue_token_pair(session, settings, user)  # saves the revoke with the new row


async def logout(session: AsyncSession, settings: Settings, refresh_token: str | None) -> None:
    """Revoke this refresh token if it is a valid one. The answer is 204 either way."""
    if not refresh_token:
        return
    try:
        claims = security.read_token(settings.jwt_secret, refresh_token, REFRESH_SCOPE)
    except jwt.InvalidTokenError:  # it already opens nothing: nothing to revoke
        return
    await repo.revoke_refresh_token(session, claims["jti"])
    await session.commit()


async def issue_token_pair(session: AsyncSession, settings: Settings, user: User) -> TokenPairOut:
    """A new access token (15 min) and refresh token (30 days); the refresh token is stored."""
    # "ver" copies the user's token_version: raising it later makes this token useless.
    access_token, _ = security.create_token(
        settings.jwt_secret, user.id, ACCESS_SCOPE, ACCESS_TOKEN_LIFETIME, ver=user.token_version
    )
    refresh_token, refresh_claims = security.create_token(
        settings.jwt_secret, user.id, REFRESH_SCOPE, REFRESH_TOKEN_LIFETIME
    )
    # Only the token's id (jti) is stored, never the token itself.
    repo.add_refresh_token(
        session,
        user.id,
        jti=refresh_claims["jti"],
        token_version=user.token_version,
        expires_at=refresh_claims["exp"],
    )
    await session.commit()
    return TokenPairOut(access_token=access_token, refresh_token=refresh_token)
