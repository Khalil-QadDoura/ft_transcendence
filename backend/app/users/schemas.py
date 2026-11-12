"""Request and response shapes of /api/users (they also appear in /api/openapi.json)."""

from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints
from pydantic_core import PydanticCustomError

from app.users.constants import BIO_MAX_LENGTH, MIN_AGE, NAME_MAX_LENGTH, POSITION_MAX_LENGTH


class UserOut(BaseModel):
    """The profile we send back. Only the fields listed here leave the server: never the
    password hash, token_version or status, and no longer phone, is_phone_verified, username
    or account_number (dropped from the contract). service.to_user_out() fills it in."""

    id: int
    email: str
    first_name: str | None
    last_name: str | None
    position: str | None
    birth_date: date | None
    bio: str | None
    avatar_object_key: str | None
    # Not a column (BE-08): the address of my picture, for <img src>. My own file under
    # avatars/, which anyone can download, or the default picture when I have none.
    avatar_url: str
    is_email_verified: bool


def age_on(day: date, birth_date: date) -> int:
    """How many full years old someone born on birth_date is on that day."""
    had_birthday = (day.month, day.day) >= (birth_date.month, birth_date.day)
    return day.year - birth_date.year - (0 if had_birthday else 1)


def old_enough(birth_date: date) -> date:
    """Refuse a birth date that makes the user younger than MIN_AGE today."""
    if age_on(date.today(), birth_date) < MIN_AGE:
        # Our own validation error: the answer is 422 "body → birth_date: You must be ...".
        raise PydanticCustomError("too_young", f"You must be at least {MIN_AGE} years old")
    return birth_date


# Spaces around a text are removed first; a name or a position cannot then be empty.
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]
Position = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=POSITION_MAX_LENGTH)
]
Bio = Annotated[str, StringConstraints(strip_whitespace=True, max_length=BIO_MAX_LENGTH)]
BirthDate = Annotated[date, AfterValidator(old_enough)]


class UserUpdate(BaseModel):
    """PATCH /api/users/me: any subset of these five fields. A field that is left out keeps
    its value, so {} changes nothing."""

    # Any other field (email, status, phone, ...) is refused with 422: PATCH cannot change
    # what it is not meant to.
    model_config = ConfigDict(extra="forbid")

    # "= None" only stands for "not sent": the service applies the fields that were sent,
    # nothing else. A field sent as null is refused (it is not a valid text or date), except
    # bio, which null empties.
    first_name: Name = None
    last_name: Name = None
    position: Position = None
    birth_date: BirthDate = None
    bio: Bio | None = None
