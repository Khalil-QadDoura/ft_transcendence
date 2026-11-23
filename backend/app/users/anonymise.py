"""The second stage of an account deletion (BE-34, Privacy Policy section 6).

DELETE /api/users/me deactivates an account at once (users/service.py) and writes deleted_at.
Every day the worker's beat runs anonymise_deleted_accounts (worker/tasks/anonymise.py): each
account deleted more than 30 days ago and not on retention hold loses its personal data, and
its files are deleted from storage. The row stays, so the account's applications, game
records and chat messages still point at it; the API shows it as "Deleted user".
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.core.storage import Storage
from app.media.constants import AVATARS_FOLDER, LOGOS_FOLDER, STAGING_FOLDER, VIDEOS_FOLDER
from app.media.models import IntroVideo
from app.users.constants import ANONYMISE_AFTER_DAYS
from app.users.models import User

log = structlog.get_logger(__name__)

# Where the browser uploads a video before confirm copies it: users/<id>/intro/<uuid>.mp4
# (media/service.py, object_key_for).
UPLOADS_FOLDER = "users"
# Rows are read again from the database under their lock, even if this session holds them.
FRESH = {"populate_existing": True}


class RunResult(NamedTuple):
    """The ids of the accounts one run anonymised, and of those it must try again."""

    anonymised: list[int]
    failed: list[int]


def anonymised_email(user_id: int) -> str:
    """The email an anonymised account keeps: unique like the id, and an address that can
    never receive mail (".invalid" is reserved for that, RFC 2606). The real email is free
    again, for a new account."""
    return f"deleted-{user_id}@invalid"


def is_due(older_than_days: int):
    """The accounts to anonymise: deleted more than older_than_days days ago (database time),
    not on hold, and not anonymised yet."""
    return (
        User.status == "deleted",
        User.deleted_at < func.now() - timedelta(days=older_than_days),
        User.retention_hold.is_(False),
        User.anonymised_at.is_(None),
    )


def folders_of(user_id: int, company_ids: list[int]) -> list[str]:
    """The storage folders that hold only this account's files: its avatars, its videos (the
    uploads and the copies confirm keeps), and the logos of each company it owned, each with
    its staging/ uploads. The "/" at the end keeps user 1 out of user 12's folder."""
    folders = [
        f"{AVATARS_FOLDER}/{user_id}/",
        f"{STAGING_FOLDER}/{AVATARS_FOLDER}/{user_id}/",
        f"{UPLOADS_FOLDER}/{user_id}/",
        f"{VIDEOS_FOLDER}/{user_id}/",
    ]
    for company_id in company_ids:
        folders.append(f"{LOGOS_FOLDER}/{company_id}/")
        folders.append(f"{STAGING_FOLDER}/{LOGOS_FOLDER}/{company_id}/")
    return folders


def delete_files(storage: Storage, keys: set[str], folders: list[str]) -> None:
    """Delete the files the rows name and every file left in the account's folders (e.g. an
    avatar whose delete failed at the first stage). MinIO calls wait for the network: this
    runs in a worker thread. A failure raises, and nothing of the account is saved."""
    for folder in folders:
        keys = keys | set(storage.keys_in(folder))
    for key in sorted(keys):
        storage.remove(key)


async def anonymise_account(
    session: AsyncSession, storage: Storage, user_id: int, older_than_days: int
) -> bool:
    """Anonymise one account in one transaction. False if it is no longer due: a hold was set,
    or another run did it, since the list was made."""
    # Lock the row and read it again, still due: the lock that the picture confirms and the
    # moderation worker take, so none of them can add a file or post a video meanwhile.
    user = await session.scalar(
        select(User).where(User.id == user_id, *is_due(older_than_days)).with_for_update(),
        execution_options=FRESH,
    )
    if user is None:
        return False
    # Then the rows that name its files, locked in the order the logo confirm uses.
    companies = (
        await session.scalars(
            select(Company).where(Company.owner_user_id == user_id).with_for_update(),
            execution_options=FRESH,
        )
    ).all()
    videos = (
        await session.scalars(
            select(IntroVideo).where(IntroVideo.user_id == user_id).with_for_update(),
            execution_options=FRESH,
        )
    ).all()

    # 1. The files first. If MinIO fails, the error leaves here before anything is saved, so
    # the account stays due and the next run tries it again from the start.
    keys = {user.avatar_object_key, *(company.logo_object_key for company in companies)}
    keys |= {video.object_key for video in videos}
    folders = folders_of(user_id, [company.id for company in companies])
    await asyncio.to_thread(delete_files, storage, keys - {None}, folders)

    # 2. Then the personal data, in one commit. The row, its applications, game records and
    # chat messages stay, linked to the same id.
    user.email = anonymised_email(user_id)
    user.password_hash = None
    user.first_name = None
    user.last_name = None
    user.position = None
    user.birth_date = None
    user.bio = None
    user.avatar_object_key = None
    user.anonymised_at = datetime.now(UTC)
    for company in companies:
        company.logo_object_key = None
    for video in videos:
        video.lifecycle_status = "deleted"
    await session.commit()
    return True


async def anonymise_deleted_accounts(
    session: AsyncSession, storage: Storage, older_than_days: int = ANONYMISE_AFTER_DAYS
) -> RunResult:
    """One run of the job: every account that is due, one transaction each, so one that fails
    (MinIO down) does not stop the others. Running it again changes nothing: an anonymised
    account is never due again. The log lines name only the account's id."""
    due = (
        await session.scalars(select(User.id).where(*is_due(older_than_days)).order_by(User.id))
    ).all()
    await session.commit()  # ends the read, so each account starts a transaction of its own
    result = RunResult(anonymised=[], failed=[])
    for user_id in due:
        try:
            if await anonymise_account(session, storage, user_id, older_than_days):
                result.anonymised.append(user_id)
                log.info("account anonymised", user_id=user_id)
        except Exception as error:
            await session.rollback()
            # The kind of error only: its text could hold an email or a name.
            log.warning(
                "account not anonymised, tried again on the next run",
                user_id=user_id,
                error=type(error).__name__,
            )
            result.failed.append(user_id)
    log.info(
        "anonymisation run finished",
        older_than_days=older_than_days,
        anonymised=len(result.anonymised),
        failed=len(result.failed),
    )
    return result
