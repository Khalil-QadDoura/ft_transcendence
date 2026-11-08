"""Request and response shapes of /api/users (they also appear in /api/openapi.json)."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    """The profile we send back. Only the fields listed here leave the server: never the
    password hash, token_version or status, and no longer phone, is_phone_verified, username
    or account_number (dropped from the contract). avatar_url comes with BE-08."""

    # Lets UserOut.model_validate(user) read the fields straight from a User row.
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    first_name: str | None
    last_name: str | None
    position: str | None
    birth_date: date | None
    bio: str | None
    avatar_object_key: str | None
    is_email_verified: bool
