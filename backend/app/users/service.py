"""The rules of the profile. Routes call these functions."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.companies import repo as companies_repo
from app.core.storage import Storage, remove_files
from app.media import service as media
from app.users.models import User
from app.users.schemas import UserOut, UserUpdate


def to_user_out(storage: Storage, user: User) -> UserOut:
    """The profile we send back. Every field is read from my row, except avatar_url: storage
    turns avatar_object_key into an address the browser can open."""
    return UserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        position=user.position,
        birth_date=user.birth_date,
        bio=user.bio,
        avatar_object_key=user.avatar_object_key,
        avatar_url=storage.avatar_url(user.avatar_object_key),
        is_email_verified=user.is_email_verified,
    )


async def update_profile(session: AsyncSession, user: User, data: UserUpdate) -> User:
    """A partial update: change only the fields the client sent, and save them."""
    # exclude_unset keeps only the fields present in the request, e.g. {"bio": "Hi"}.
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    # SQLAlchemy writes one UPDATE with only the changed columns (and updated_at).
    await session.commit()
    return user


async def delete_account(session: AsyncSession, storage: Storage, user: User) -> None:
    """Soft delete: the row stays, only its status becomes "deleted".

    That one change is enough to lock the account: login (auth/service.py) and every
    protected request and refresh (auth/deps.py, auth/service.py) check that the status is
    "active", so the user's tokens stop working at once and logging in again gets 401.

    The pictures cannot just be hidden: anyone who kept the address of a file under avatars/
    or logos/ could still download it. So the avatar and the logo of my company are emptied,
    and once that is saved, their files are deleted from storage at once (BE-08).

    My company is soft-deleted with me, in the same transaction: once its only owner is gone,
    nobody can run it or answer its candidates. The job pages and the job search show only
    the jobs of active companies, so its jobs disappear from them too. The jobs and the
    applications already sent stay in the database as they are.

    deleted_at starts the 30 days after which the worker's daily job anonymises the account
    (BE-34, users/anonymise.py).
    """
    old_files = await media.forget_pictures(session, user)
    user.status = "deleted"
    user.deleted_at = datetime.now(UTC)
    # My company, locked as DELETE /companies locks it (forget_pictures already holds this
    # lock, so it never waits here). A company that DELETE /companies deleted first is not
    # found. Its logo is already emptied, and its file is in old_files: it is deleted once.
    company = await companies_repo.get_active_by_owner_id(session, user.id, lock=True)
    if company is not None:
        # soft_delete commits: that one commit saves my status, my emptied pictures and the
        # deleted company together. If it fails, none of them is saved.
        await companies_repo.soft_delete(session, company)
    else:
        await session.commit()
    await remove_files(storage, old_files)
