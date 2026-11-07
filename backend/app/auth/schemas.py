"""Request and response shapes of /api/auth (they also appear in /api/openapi.json)."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.auth.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

# A valid email address, in lower case: Ana@Example.com and ana@example.com are one account.
Email = Annotated[EmailStr, AfterValidator(str.lower)]


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
