"""The /api/users endpoints. Each one needs the logged-in user (CurrentUser)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.db.session import get_session
from app.users import service
from app.users.schemas import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])  # mounted under /api

# The same session CurrentUser used to load the user: FastAPI makes one per request.
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/me")
async def get_me(user: CurrentUser) -> UserOut:
    """My own profile. CurrentUser has already loaded my row, so there is nothing to query."""
    return UserOut.model_validate(user)


@router.patch("/me")
async def update_me(user: CurrentUser, data: UserUpdate, session: Session) -> UserOut:
    """Change any of first_name, last_name, position, birth_date and bio; the rest stays."""
    user = await service.update_profile(session, user, data)
    return UserOut.model_validate(user)
