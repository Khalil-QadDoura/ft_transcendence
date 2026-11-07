"""The rules of sign-up and login. Routes call these functions; these call the repo."""

import asyncio

import jwt
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.exc import IntegrityError
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
    user = await repo.get_user_by_email(session, data.email)
    if user is not None and user.is_email_verified:
        raise HTTPException(status_code=409, detail=EMAIL_TAKEN)
    if user is None:
        user = repo.add_user(session, data.email)
    # Signing up again before verifying keeps the one account, with the newest password.
    # Argon2 is slow on purpose, so it runs in a worker thread: meanwhile the server keeps
    # answering other requests.
    user.password_hash = await asyncio.to_thread(security.hash_password, data.password)
    try:
        await session.commit()
    except IntegrityError:  # the same email signed up at the same moment (uq_users_email)
        raise HTTPException(status_code=409, detail=EMAIL_TAKEN) from None

    token, _ = security.create_token(
        settings.jwt_secret, user.id, EMAIL_VERIFY_SCOPE, EMAIL_VERIFY_TOKEN_LIFETIME
    )
    # The link opens the frontend's page, which calls GET /api/auth/verify with the token.
    link = f"{settings.frontend_base_url.rstrip('/')}/verify-email?token={token}"
    # Sent after the answer has gone out (202 Accepted: the work is not finished yet).
    background.add_task(mailer.send, user.email, VERIFY_SUBJECT, VERIFY_BODY.format(link=link))


async def verify_email(session: AsyncSession, settings: Settings, token: str) -> VerifyOut:
    """Mark the email of the token's user as verified. Opening the link twice is fine."""
    try:
        claims = security.read_token(settings.jwt_secret, token, EMAIL_VERIFY_SCOPE)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail=INVALID_LINK) from None
    user = await repo.get_user_by_id(session, int(claims["sub"]))
    if user is None or user.status != "active":
        raise HTTPException(status_code=400, detail=INVALID_LINK)
    updated = not user.is_email_verified
    user.is_email_verified = True
    await session.commit()
    return VerifyOut(verified=True, email=user.email, updated=updated)


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


async def issue_token_pair(session: AsyncSession, settings: Settings, user: User) -> TokenPairOut:
    """A new access token (15 min) and refresh token (30 days); the refresh token is stored."""
    # "ver" copies the user's token_version: raising it later makes this token useless.
    access_token, _ = security.create_token(
        settings.jwt_secret, user.id, ACCESS_SCOPE, ACCESS_TOKEN_LIFETIME, ver=user.token_version
    )
    refresh_token, refresh = security.create_token(
        settings.jwt_secret, user.id, REFRESH_SCOPE, REFRESH_TOKEN_LIFETIME
    )
    # Only the token's id (jti) is stored, never the token itself.
    repo.add_refresh_token(
        session,
        user.id,
        jti=refresh["jti"],
        token_version=user.token_version,
        expires_at=refresh["exp"],
    )
    await session.commit()
    return TokenPairOut(access_token=access_token, refresh_token=refresh_token)
