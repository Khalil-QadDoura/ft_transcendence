"""The /api/users endpoints. Each one needs the logged-in user (CurrentUser)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.storage import Storage, get_storage
from app.db.session import get_session
from app.users import service
from app.users.schemas import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])  # mounted under /api

# The same session CurrentUser used to load the user: FastAPI makes one per request.
Session = Annotated[AsyncSession, Depends(get_session)]
# To write avatar_url (making the address does not connect to MinIO), and to delete my
# pictures' files with my account.
Files = Annotated[Storage, Depends(get_storage)]


@router.get("/me")
async def get_me(user: CurrentUser, storage: Files) -> UserOut:
    """My own profile. CurrentUser has already loaded my row, so there is nothing to query."""
    return service.to_user_out(storage, user)


@router.patch("/me")
async def update_me(
    user: CurrentUser, data: UserUpdate, session: Session, storage: Files
) -> UserOut:
    """Change any of first_name, last_name, position, birth_date and bio; the rest stays."""
    user = await service.update_profile(session, user, data)
    return service.to_user_out(storage, user)


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, session: Session, storage: Files) -> None:
    """Delete my account (a soft delete). My tokens stop working and I cannot log in again;
    my company is soft-deleted too, and the files of my avatar and of its logo are deleted."""
    await service.delete_account(session, storage, user)
