"""The fixed numbers and names of sign-up and login, in one place."""

from datetime import timedelta

# How long each kind of token works.
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)
EMAIL_VERIFY_TOKEN_LIFETIME = timedelta(hours=24)

# Every token says what it is for (its "scope" claim), so one kind cannot be used as another.
ACCESS_SCOPE = "access"
REFRESH_SCOPE = "refresh"
EMAIL_VERIFY_SCOPE = "email_verify"

# Password length allowed at sign-up (api-contract.md).
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# Requests allowed per client IP (api-contract.md, "Rate limit").
REGISTER_RATE_LIMIT = "5/minute"
LOGIN_RATE_LIMIT = "10/minute"
REFRESH_RATE_LIMIT = "20/minute"
