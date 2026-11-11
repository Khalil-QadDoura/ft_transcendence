"""Request and response shapes of /api/auth (they also appear in /api/openapi.json)."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.auth.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

# A valid email address, in lower case: Ana@Example.com and ana@example.com are one account.
Email = Annotated[EmailStr, AfterValidator(str.lower)]

# A new password, on a change or a reset: the same rule as at sign-up (RegisterIn).
NewPassword = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]


class RegisterIn(BaseModel):
    email: Email
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class MessageOut(BaseModel):
    message: str


class VerifyOut(BaseModel):
    verified: bool
    email: str
    # False when the email was already verified (the link was opened before).
    updated: bool


class LoginIn(BaseModel):
    email: Email
    # No minimum here: a wrong password simply fails. The maximum caps the hashing work.
    password: str = Field(max_length=PASSWORD_MAX_LENGTH)


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    # Optional: logout always answers 204, even with no token or a bad one.
    refresh_token: str | None = None


class ChangePasswordIn(BaseModel):
    # No minimum, as at login: a wrong current password simply fails.
    current_password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    new_password: NewPassword
