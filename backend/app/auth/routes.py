"""The /api/auth endpoints. Thin: each one checks the input (schemas) and calls the service."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.constants import LOGIN_RATE_LIMIT, REGISTER_RATE_LIMIT
from app.auth.schemas import LoginIn, MessageOut, RegisterIn, TokenPairOut, VerifyOut
from app.core.limiter import limiter
from app.core.mailer import Mailer, get_mailer
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])  # mounted under /api

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/register", status_code=202)
@limiter.limit(REGISTER_RATE_LIMIT)
async def register(
    request: Request,
    data: RegisterIn,
    session: Session,
    mailer: Annotated[Mailer, Depends(get_mailer)],
    background: BackgroundTasks,
) -> MessageOut:
    """Sign up. The account works once the email is verified with the link we send."""
    await service.register(session, request.app.state.settings, mailer, background, data)
    return MessageOut(message="Check your email for the verification link")


@router.get("/verify")
async def verify(request: Request, token: str, session: Session) -> VerifyOut:
    """Called by the frontend's /verify-email page with the token from the email's link."""
    return await service.verify_email(session, request.app.state.settings, token)


@router.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT)
async def login(request: Request, data: LoginIn, session: Session) -> TokenPairOut:
    """Log in: 401 for a wrong email or password, 403 while the email is not verified."""
    return await service.login(session, request.app.state.settings, data)
