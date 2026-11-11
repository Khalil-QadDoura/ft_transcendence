"""HTTP endpoints for company profile management."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.companies import service
from app.companies.schemas import CompanyCreate, CompanyOut, CompanyUpdate
from app.db.session import get_session

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/me", response_model=CompanyOut | None)
async def get_my_company(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> CompanyOut | None:
    """Returns the company owned by the current user, or null if they own none (BE-21)."""
    return await service.get_my_company(session, user.id)


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def create_my_company(
    payload: CompanyCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> CompanyOut:
    """Registers a new company. Each employer user can own at most one active company."""
    return await service.create_my_company(session, user.id, payload)


@router.patch("/me", response_model=CompanyOut)
async def patch_my_company(
    payload: CompanyUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> CompanyOut:
    """Updates company details for the current user's active company."""
    return await service.patch_my_company(session, user.id, payload)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_company(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> None:
    """Soft-deletes the current user's active company. Idempotent."""
    await service.delete_my_company(session, user.id)
