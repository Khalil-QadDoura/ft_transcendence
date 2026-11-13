"""get_current_user: the one login check that every protected route uses (BE-05 and later)."""

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import repo, security
from app.auth.constants import ACCESS_SCOPE
from app.db.session import get_session
from app.users.models import User

# Reads the "Authorization: Bearer <access token>" header (and adds Swagger's Authorize
# button). auto_error=False: a missing header gives None, and we answer the 401 ourselves.
bearer = HTTPBearer(auto_error=False)


def unauthorized(detail: str) -> HTTPException:
    # The WWW-Authenticate header tells the client what to send (HTTP standard for 401).
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


async def _resolve_user(request: Request, token: str, session: AsyncSession) -> User:
    secret = request.app.state.settings.jwt_secret
    try:
        claims = security.read_token(secret, token, ACCESS_SCOPE)
    except jwt.InvalidTokenError:  # changed, expired, or not an access token
        raise unauthorized("Invalid or expired token") from None
    user = await repo.get_user_by_id(session, int(claims["sub"]))
    # Checked on every request: once token_version goes up (a password change or reset,
    # BE-04), every token made before it stops working, on every device at once.
    if user is None or user.status != "active" or claims.get("ver") != user.token_version:
        raise unauthorized("Invalid or expired token")
    return user


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """The logged-in user of this request, or 401."""
    if credentials is None:
        raise unauthorized("Not authenticated")
    return await _resolve_user(request, credentials.credentials, session)


async def get_current_user_optional(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User | None:
    """The logged-in user if Bearer credentials are provided, else None (401 on invalid token)."""
    if credentials is None:
        return None
    return await _resolve_user(request, credentials.credentials, session)


# What a protected route asks for: `async def me(user: CurrentUser): ...`
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
