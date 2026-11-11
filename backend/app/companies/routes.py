"""HTTP endpoints for company profile management."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.companies import service
from app.companies.schemas import CompanyCreate, CompanyOut, CompanyUpdate
from app.core.storage import Storage, get_storage
from app.db.session import get_session

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/me", response_model=CompanyOut | None)
async def get_my_company(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    storage: Annotated[Storage, Depends(get_storage)],
) -> CompanyOut | None:
    """Returns the company owned by the current user, or null if they own none (BE-21)."""
    company = await service.get_my_company(session, user.id)
    return None if company is None else service.to_company_out(storage, company)


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def create_my_company(
    payload: CompanyCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    storage: Annotated[Storage, Depends(get_storage)],
) -> CompanyOut:
    """Registers a new company. Each employer user can own at most one active company."""
    company = await service.create_my_company(session, user.id, payload)
    return service.to_company_out(storage, company)


@router.patch("/me", response_model=CompanyOut)
async def patch_my_company(
    payload: CompanyUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    storage: Annotated[Storage, Depends(get_storage)],
) -> CompanyOut:
    """Updates company details for the current user's active company."""
    company = await service.patch_my_company(session, user.id, payload)
    return service.to_company_out(storage, company)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_company(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    storage: Annotated[Storage, Depends(get_storage)],
) -> None:
    """Soft-deletes the current user's active company (and deletes its logo file). Idempotent."""
    await service.delete_my_company(session, storage, user.id)
