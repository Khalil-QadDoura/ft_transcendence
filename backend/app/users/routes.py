"""The /api/users endpoints. Each one needs the logged-in user (CurrentUser)."""

from fastapi import APIRouter

from app.auth.deps import CurrentUser
from app.users.schemas import UserOut

router = APIRouter(prefix="/users", tags=["users"])  # mounted under /api


@router.get("/me")
async def get_me(user: CurrentUser) -> UserOut:
    """My own profile. CurrentUser has already loaded my row, so there is nothing to query."""
    return UserOut.model_validate(user)
