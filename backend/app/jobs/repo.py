"""Database queries for the jobs domain (BE-25)."""

from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, cast, func, literal_column, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application, JobView
from app.companies.models import Company
from app.companies.repo import ACTIVE as COMPANY_ACTIVE
from app.jobs.models import GeographyPoint, Job

DRAFT = "draft"
OPEN = "open"
DELETED = "deleted"
MAX_ID = 2**63 - 1
MAX_RADIUS_KM = 500.0
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100


def _counters_subqueries():
    views_sub = (
        select(
            JobView.job_id.label("job_id"),
            func.count(JobView.id).label("views_count"),
        )
        .group_by(JobView.job_id)
        .subquery()
    )
    apps_sub = (
        select(
            Application.job_id.label("job_id"),
            func.count(case((Application.status != "withdrawn", 1))).label("applications_count"),
            func.count(case((Application.status == "submitted", 1))).label(
                "new_applications_count"
            ),
        )
        .group_by(Application.job_id)
        .subquery()
    )
    return views_sub, apps_sub


def _build_jobs_query():
    views_sub, apps_sub = _counters_subqueries()
    stmt = (
        select(
            Job,
            Company.name.label("company_name"),
            Company.logo_object_key.label("company_logo_key"),
            Company.owner_user_id.label("company_owner_user_id"),
            func.coalesce(views_sub.c.views_count, 0).label("views_count"),
            func.coalesce(apps_sub.c.applications_count, 0).label("applications_count"),
            func.coalesce(apps_sub.c.new_applications_count, 0).label("new_applications_count"),
        )
        .join(Company, Company.id == Job.owner_id)
        .outerjoin(views_sub, views_sub.c.job_id == Job.id)
        .outerjoin(apps_sub, apps_sub.c.job_id == Job.id)
        .where(Job.status != DELETED, Company.status == COMPANY_ACTIVE)
    )
    return stmt


def job_to_dict(
    job: Job,
    *,
    company_name: str | None,
    company_logo_key: str | None = None,
    views_count: int = 0,
    applications_count: int = 0,
    new_applications_count: int = 0,
    distance_km: float | None = None,
    company_owner_user_id: int | None = None,
) -> dict[str, Any]:
    """Flatten a Job ORM row with company and counter columns into schema kwargs."""
    data: dict[str, Any] = {
        "id": job.id,
        "owner_id": job.owner_id,
        "company_name": company_name,
        "company_logo_key": company_logo_key,
        "title": job.title,
        "description": job.description,
        "status": job.status,
        "latitude": job.latitude,
        "longitude": job.longitude,
        "location": job.location,
        "salary_amount": job.salary_amount,
        "salary_type": job.salary_type,
        "salary_currency": job.salary_currency,
        "schedule": job.schedule,
        "urgency": job.urgency,
        "views_count": int(views_count or 0),
        "applications_count": int(applications_count or 0),
        "new_applications_count": int(new_applications_count or 0),
        "distance_km": distance_km,
        "created_by_id": job.created_by_id,
        "updated_by_id": job.updated_by_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }
    if company_owner_user_id is not None:
        data["company_owner_user_id"] = company_owner_user_id
    return data


async def get_job_detail(session: AsyncSession, job_id: int) -> dict[str, Any] | None:
    """Return a non-deleted job with its active company and counters, or None."""
    stmt = _build_jobs_query().where(Job.id == job_id).limit(1)
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None
    return job_to_dict(
        row.Job,
        company_name=row.company_name,
        company_logo_key=row.company_logo_key,
        company_owner_user_id=row.company_owner_user_id,
        views_count=row.views_count,
        applications_count=row.applications_count,
        new_applications_count=row.new_applications_count,
    )


async def list_company_jobs(session: AsyncSession, company_id: int) -> list[dict[str, Any]]:
    """Return all non-deleted jobs for one company with view and application counters."""
    stmt = (
        _build_jobs_query()
        .where(Job.owner_id == company_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        job_to_dict(
            row.Job,
            company_name=row.company_name,
            company_logo_key=row.company_logo_key,
            views_count=row.views_count,
            applications_count=row.applications_count,
            new_applications_count=row.new_applications_count,
        )
        for row in rows
    ]


async def get_owned_job(session: AsyncSession, job_id: int, owner_user_id: int) -> Job | None:
    """Return a non-deleted job only if owned by the caller's active company."""
    stmt = (
        select(Job)
        .join(Company, Company.id == Job.owner_id)
        .where(
            Job.id == job_id,
            Job.status != DELETED,
            Company.status == COMPANY_ACTIVE,
            Company.owner_user_id == owner_user_id,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_job(
    session: AsyncSession,
    *,
    owner_id: int,
    actor_id: int,
    values: dict[str, Any],
) -> Job:
    """Insert a new job row; PostgreSQL computes location_point and search_vector."""
    job = Job(
        owner_id=owner_id,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        **values,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _conditional_job_update(
    session: AsyncSession,
    job: Job,
    *,
    actor_id: int,
    values: dict[str, Any],
) -> bool:
    """Update a job only while status != 'deleted'; returns False if concurrently deleted."""
    allowed_values = {k: v for k, v in values.items() if hasattr(Job, k)}
    stmt = (
        update(Job)
        .where(Job.id == job.id, Job.status != DELETED)
        .values(**allowed_values, updated_by_id=actor_id)
        .returning(Job.id)
    )
    updated_id = (await session.execute(stmt)).scalar_one_or_none()
    if updated_id is None:
        await session.rollback()
        return False
    await session.commit()
    # Invalidate the loaded ORM instance because async_sessionmaker sets expire_on_commit=False.
    session.expire(job)
    return True


async def update_job(
    session: AsyncSession,
    job: Job,
    *,
    actor_id: int,
    values: dict[str, Any],
) -> bool:
    """Persist field changes onto an owned job row if still non-deleted."""
    return await _conditional_job_update(session, job, actor_id=actor_id, values=values)


async def soft_delete_job(session: AsyncSession, job: Job, *, actor_id: int) -> bool:
    """Soft-delete a job by setting status to 'deleted' if still non-deleted."""
    return await _conditional_job_update(
        session, job, actor_id=actor_id, values={"status": DELETED}
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _origin_geography(lat: float, lng: float):
    return cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), GeographyPoint())


async def get_job_distance_meters(
    session: AsyncSession, job_id: int, *, lat: float, lng: float
) -> float | None:
    """Return distance in meters from (lat, lng) for a cursor job id, or None if not visible."""
    stmt = (
        select(func.ST_Distance(Job.location_point, _origin_geography(lat, lng)))
        .join(Company, Company.id == Job.owner_id)
        .where(
            Job.id == job_id,
            Job.status == OPEN,
            Company.status == COMPANY_ACTIVE,
        )
    )
    val = (await session.execute(stmt)).scalar_one_or_none()
    return float(val) if val is not None else None


async def search_open_jobs(
    session: AsyncSession,
    *,
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float | None = None,
    schedule: str | None = None,
    salary_min: Decimal | None = None,
    salary_max: Decimal | None = None,
    urgency: str | None = None,
    keyword: str | None = None,
    position: str | None = None,
    sort_by: str = "newest",
    cursor: int | None = None,
    cursor_distance_m: float | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[dict[str, Any]]:
    """Search open jobs of active companies with PostGIS radius, FTS, filters, sort, and cursor."""
    views_sub, apps_sub = _counters_subqueries()
    has_coords = lat is not None and lng is not None
    origin = _origin_geography(lat, lng) if has_coords else None
    dist_expr = func.ST_Distance(Job.location_point, origin) if origin is not None else None

    stmt = (
        select(
            Job,
            Company.name.label("company_name"),
            Company.logo_object_key.label("company_logo_key"),
            func.coalesce(views_sub.c.views_count, 0).label("views_count"),
            func.coalesce(apps_sub.c.applications_count, 0).label("applications_count"),
            (
                dist_expr.label("distance_m")
                if dist_expr is not None
                else literal_column("NULL").label("distance_m")
            ),
        )
        .join(Company, Company.id == Job.owner_id)
        .outerjoin(views_sub, views_sub.c.job_id == Job.id)
        .outerjoin(apps_sub, apps_sub.c.job_id == Job.id)
        .where(Job.status == OPEN, Company.status == COMPANY_ACTIVE)
    )

    if origin is not None and radius_km is not None:
        stmt = stmt.where(func.ST_DWithin(Job.location_point, origin, radius_km * 1000.0))

    if position:
        stmt = stmt.where(Job.title.ilike(f"%{_escape_like(position)}%", escape="\\"))

    if schedule is not None:
        stmt = stmt.where(Job.schedule == schedule)

    if salary_min is not None:
        stmt = stmt.where(Job.salary_amount >= salary_min)

    if salary_max is not None:
        stmt = stmt.where(Job.salary_amount <= salary_max)

    if urgency is not None:
        stmt = stmt.where(Job.urgency == urgency)

    if keyword:
        stmt = stmt.where(
            text("jobs.search_vector @@ plainto_tsquery('english', :kw)").bindparams(kw=keyword)
        )

    if sort_by == "nearest" and dist_expr is not None:
        if cursor is not None and cursor_distance_m is not None:
            stmt = stmt.where(
                or_(
                    dist_expr > cursor_distance_m,
                    and_(dist_expr == cursor_distance_m, Job.id < cursor),
                )
            )
        stmt = stmt.order_by(dist_expr.asc(), Job.id.desc())
    else:
        if cursor is not None:
            stmt = stmt.where(Job.id < cursor)
        stmt = stmt.order_by(Job.id.desc())

    stmt = stmt.limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    return [
        job_to_dict(
            row.Job,
            company_name=row.company_name,
            company_logo_key=row.company_logo_key,
            views_count=row.views_count,
            applications_count=row.applications_count,
            new_applications_count=0,
            distance_km=round(float(row.distance_m) / 1000.0, 1)
            if row.distance_m is not None
            else None,
        )
        for row in rows
    ]
