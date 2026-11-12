"""Database queries for the companies domain."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.media.constants import ROW_LOCK

ACTIVE = "active"
DELETED = "deleted"


async def get_active_by_owner_id(
    session: AsyncSession, owner_user_id: int, lock: bool = False
) -> Company | None:
    """Finds the single active company owned by a user.

    lock=True also locks its row until the commit, as a logo confirm does (ROW_LOCK, BE-08),
    first waiting for a request that holds it. PostgreSQL then checks the row again as that
    request left it: a company it deleted is not found, and its new logo key is the one read.
    """
    stmt = (
        select(Company)
        .where(Company.owner_user_id == owner_user_id, Company.status == ACTIVE)
        .limit(1)
    )
    if lock:
        # populate_existing: the row read now, even if this session had loaded it before.
        stmt = stmt.with_for_update(**ROW_LOCK).execution_options(populate_existing=True)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    owner_user_id: int,
    name: str,
    description: str | None = None,
    country: str | None = None,
    city: str | None = None,
    district: str | None = None,
    country_code: str | None = None,
) -> Company:
    """Creates a new active company."""
    company = Company(
        owner_user_id=owner_user_id,
        name=name.strip(),
        description=description.strip() if description else None,
        country=country.strip() if country else None,
        city=city.strip() if city else None,
        district=district.strip() if district else None,
        country_code=country_code,
        status=ACTIVE,
    )
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company


async def update_company(
    session: AsyncSession,
    company: Company,
    values: dict,
) -> Company:
    """Applies field updates to an active company."""
    for key, value in values.items():
        if hasattr(company, key):
            setattr(company, key, value)
    await session.commit()
    await session.refresh(company)
    return company


async def soft_delete(session: AsyncSession, company: Company) -> None:
    """Marks a company as deleted (soft delete)."""
    await session.execute(update(Company).where(Company.id == company.id).values(status=DELETED))
    await session.commit()
