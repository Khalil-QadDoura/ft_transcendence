"""Business logic and rules for the companies domain."""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies import repo
from app.companies.models import Company
from app.companies.schemas import CompanyCreate, CompanyUpdate


async def get_my_company(session: AsyncSession, user_id: int) -> Company | None:
    """Returns the user's active company, or None if the user owns no company.

    Important (BE-21 / Issue #15): Does NOT raise 404 so that regular job-seeker
    requests return 200 with null instead of logging a console error.
    """
    return await repo.get_active_by_owner_id(session, user_id)


async def create_my_company(session: AsyncSession, user_id: int, payload: CompanyCreate) -> Company:
    """Creates a new company for the user. Raises 409 if an active company exists."""
    existing = await repo.get_active_by_owner_id(session, user_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active company already exists",
        )

    try:
        return await repo.create(
            session,
            owner_user_id=user_id,
            name=payload.name,
            description=payload.description,
            country=payload.country,
            city=payload.city,
            district=payload.district,
        )
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active company already exists",
        ) from None


async def patch_my_company(session: AsyncSession, user_id: int, payload: CompanyUpdate) -> Company:
    """Updates an existing company. Raises 404 if no active company exists."""
    company = await repo.get_active_by_owner_id(session, user_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )

    update_data = {
        "name": payload.name.strip(),
        "country": payload.country.strip(),
        "city": payload.city.strip(),
        "district": payload.district.strip() if (payload.district or "").strip() else None,
        "country_code": payload.country_code,
    }
    return await repo.update_company(session, company, update_data)


async def delete_my_company(session: AsyncSession, user_id: int) -> None:
    """Soft-deletes the user's active company. Idempotent if no active company exists."""
    company = await repo.get_active_by_owner_id(session, user_id)
    if not company:
        return
    await repo.soft_delete(session, company)


async def get_active_company_id(session: AsyncSession, user_id: int) -> int:
    """Returns the active company id for an owner, or raises 404."""
    company = await repo.get_active_by_owner_id(session, user_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active company not found",
        )
    return company.id
