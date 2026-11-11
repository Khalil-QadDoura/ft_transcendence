"""The /api/auth endpoints. Thin: each one checks the input (schemas) and calls the service."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.constants import (
    CHANGE_PASSWORD_RATE_LIMIT,
    FORGOT_PASSWORD_RATE_LIMIT,
    LOGIN_RATE_LIMIT,
    REFRESH_RATE_LIMIT,
    REGISTER_RATE_LIMIT,
)
from app.auth.deps import CurrentUser
from app.auth.schemas import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    LogoutIn,
    MessageOut,
    RefreshIn,
    RegisterIn,
    TokenPairOut,
    VerifyOut,
)
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


@router.post("/refresh")
@limiter.limit(REFRESH_RATE_LIMIT)
async def refresh(request: Request, data: RefreshIn, session: Session) -> TokenPairOut:
    """A new token pair for a refresh token, which then stops working (rotation)."""
    return await service.refresh(session, request.app.state.settings, data.refresh_token)


@router.post("/logout", status_code=204)
async def logout(request: Request, session: Session, data: LogoutIn | None = None) -> None:
    """Log out this session: its refresh token stops working. Always 204."""
    refresh_token = data.refresh_token if data else None
    await service.logout(session, request.app.state.settings, refresh_token)


@router.post("/change-password", status_code=204)
@limiter.limit(CHANGE_PASSWORD_RATE_LIMIT)
async def change_password(
    request: Request, data: ChangePasswordIn, user: CurrentUser, session: Session
) -> None:
    """Change my password. All my tokens stop working, on every device: I log in again."""
    await service.change_password(session, user, data)


@router.post("/forgot-password", status_code=202)
@limiter.limit(FORGOT_PASSWORD_RATE_LIMIT)
async def forgot_password(
    request: Request,
    data: ForgotPasswordIn,
    session: Session,
    mailer: Annotated[Mailer, Depends(get_mailer)],
    background: BackgroundTasks,
) -> MessageOut:
    """Ask for a reset link by email. Always the same 202, whether the email has an account
    or not, so nobody can use this to find out which emails have one."""
    await service.forgot_password(
        session, request.app.state.settings, mailer, background, data.email
    )
    return MessageOut(message="If this email has an account, a reset link is on its way")
