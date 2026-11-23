"""The /api/auth endpoints. Thin: each one checks the input (schemas) and calls the service."""

from typing import Annotated
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import oauth42, service
from app.auth.constants import (
    OAUTH_CALLBACK_PATH,
    OAUTH_FRONTEND_PATH,
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_LIFETIME,
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
    ResetPasswordIn,
    TokenPairOut,
    VerifyOut,
)
from app.core.limiter import limiter
from app.core.limits import (
    CHANGE_PASSWORD_RATE_LIMIT,
    FORGOT_PASSWORD_RATE_LIMIT,
    LOGIN_RATE_LIMIT,
    OAUTH_START_RATE_LIMIT,
    REFRESH_RATE_LIMIT,
    REGISTER_RATE_LIMIT,
    RESET_PASSWORD_RATE_LIMIT,
)
from app.core.mailer import Mailer, get_mailer
from app.core.redis_client import get_redis
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])  # mounted under /api
log = structlog.get_logger(__name__)

Session = Annotated[AsyncSession, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]


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


@router.post("/reset-password", status_code=204)
@limiter.limit(RESET_PASSWORD_RATE_LIMIT)
async def reset_password(request: Request, data: ResetPasswordIn, session: Session) -> None:
    """Called by the frontend's /reset-password page with the token from the email's link
    and the new password. All the user's tokens stop working."""
    await service.reset_password(session, data)


@router.get("/oauth/42/start", response_class=RedirectResponse, status_code=302)
@limiter.limit(OAUTH_START_RATE_LIMIT)
async def oauth42_start(request: Request, redis: RedisClient) -> RedirectResponse:
    """The "Log in with 42" button opens this. It sends the browser on to 42's login page.
    503 when this server has no 42 keys (FT_CLIENT_ID, FT_CLIENT_SECRET)."""
    settings = request.app.state.settings
    state = await service.start_oauth42(settings, redis)
    response = RedirectResponse(oauth42.authorize_url(settings, state), status_code=302)
    # The same state goes into a cookie of this browser; the callback checks that they match.
    # HttpOnly: page scripts cannot read it. Secure: HTTPS only. SameSite=Lax: still sent when
    # 42 sends the browser back to us. Its path: sent to the callback and nowhere else.
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=int(OAUTH_STATE_LIFETIME.total_seconds()),
        path=OAUTH_CALLBACK_PATH,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/oauth/42/callback", response_class=RedirectResponse, status_code=302)
async def oauth42_callback(
    request: Request,
    session: Session,
    redis: RedisClient,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """42 sends the browser back here after its login page, with a code (or an error) and our
    state. Always answers with a redirect to the frontend's /oauth/callback page: with our
    token pair after the "#", or with #error=<reason>."""
    settings = request.app.state.settings
    try:
        pair = await service.finish_oauth42(
            session,
            settings,
            redis,
            state=state,
            cookie_state=request.cookies.get(OAUTH_STATE_COOKIE),
            code=code,
            error=error,
        )
        fragment = urlencode(pair.model_dump())
    except service.OAuthLoginError as failure:
        log.info("login with 42 refused", reason=failure.code)
        fragment = urlencode({"error": failure.code})
    # The tokens go after "#" (the fragment), never after "?" (the query string): the browser
    # keeps the fragment to itself, so it never reaches a server, a proxy or a log.
    frontend_page = settings.frontend_base_url.rstrip("/") + OAUTH_FRONTEND_PATH
    response = RedirectResponse(f"{frontend_page}#{fragment}", status_code=302)
    response.headers["Cache-Control"] = "no-store"  # never keep this answer in a cache
    response.headers["Referrer-Policy"] = "no-referrer"
    # The state is used up: the browser can forget it.
    response.delete_cookie(
        OAUTH_STATE_COOKIE, path=OAUTH_CALLBACK_PATH, secure=True, httponly=True, samesite="lax"
    )
    return response
