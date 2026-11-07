"""The rules of sign-up and login. Routes call these functions; these call the repo."""

import asyncio

import jwt
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import repo, security
from app.auth.constants import EMAIL_VERIFY_SCOPE, EMAIL_VERIFY_TOKEN_LIFETIME
from app.auth.schemas import RegisterIn, VerifyOut
from app.core.config import Settings
from app.core.mailer import Mailer

EMAIL_TAKEN = "Email already registered"
INVALID_LINK = "Invalid or expired link"

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
