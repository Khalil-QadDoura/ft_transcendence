"""The daily job that anonymises deleted accounts (BE-34), and the same run on demand.

The worker's beat starts anonymise_deleted once a day (worker/celery_app.py). For the demo,
`make anonymise-deleted days=0` runs it at once in the worker container:

    python -m app.worker.tasks.anonymise --older-than-days 0

Accounts on retention hold are skipped either way. users/anonymise.py has the rules.
"""

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.storage import Storage
from app.users.anonymise import RunResult, anonymise_deleted_accounts
from app.users.constants import ANONYMISE_AFTER_DAYS
from app.worker.celery_app import celery_app

ANONYMISE_TASK = "app.worker.tasks.anonymise.anonymise_deleted"


async def run(older_than_days: int, settings: Settings | None = None) -> RunResult:
    """One run on the database and the bucket of these settings."""
    cfg = settings or get_settings()
    engine = create_async_engine(cfg.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await anonymise_deleted_accounts(session, Storage(cfg), older_than_days)
    finally:
        await engine.dispose()


@celery_app.task(name=ANONYMISE_TASK)
def anonymise_deleted(older_than_days: int = ANONYMISE_AFTER_DAYS) -> list[int]:
    """The daily beat task: the ids of the accounts it anonymised."""
    return asyncio.run(run(older_than_days)).anonymised


def main(argv: list[str] | None = None) -> int:
    """The command: exit code 1 if an account could not be anonymised (it is tried again on
    the next run), 0 otherwise."""
    parser = argparse.ArgumentParser(
        prog="python -m app.worker.tasks.anonymise",
        description="Anonymise the deleted accounts that are due (never those on hold).",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=ANONYMISE_AFTER_DAYS,
        help=f"only accounts deleted more than this many days ago (default "
        f"{ANONYMISE_AFTER_DAYS}; 0 for the demo: every deleted account)",
    )
    args = parser.parse_args(argv)
    if args.older_than_days < 0:
        parser.error("--older-than-days must be 0 or more")
    settings = get_settings()
    configure_logging(settings.log_level)
    result = asyncio.run(run(args.older_than_days, settings))
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
