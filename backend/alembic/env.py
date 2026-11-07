"""Alembic runs this file for every migration command. The database URL comes from our settings."""

import asyncio
import warnings

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Each domain's models module is imported once here, so Base.metadata knows every table
# (autogenerate and `alembic check` compare it with the database).
import app.applications.models  # noqa: F401
import app.auth.models  # noqa: F401
import app.companies.models  # noqa: F401
import app.conversations.models  # noqa: F401
import app.friends.models  # noqa: F401
import app.jobs.models  # noqa: F401
import app.media.models  # noqa: F401
import app.users.models  # noqa: F401
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base

settings = get_settings()
configure_logging(settings.log_level)
target_metadata = Base.metadata

# SQLAlchemy cannot read PostGIS's geography type back from the database. That is expected
# (jobs.location_point is compared by name only), so do not warn about it.
warnings.filterwarnings("ignore", message="Did not recognize type 'geography'")


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    """Compare only the tables our models describe.

    PostGIS brings tables of its own (spatial_ref_sys, and the tiger and topology schemas,
    which the postgis image puts on the search path); autogenerate must leave them alone.
    The catch: a table removed from the models is not noticed, so write its op.drop_table.
    """
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_name=include_name
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    """Connect to the database and apply the migrations."""
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    # `alembic upgrade head --sql` prints the SQL instead of running it.
    context.configure(
        url=settings.database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
