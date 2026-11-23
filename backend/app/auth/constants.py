"""The fixed numbers and names of sign-up and login, in one place."""

from datetime import timedelta

# How long each kind of token works.
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)
EMAIL_VERIFY_TOKEN_LIFETIME = timedelta(hours=24)
PASSWORD_RESET_TOKEN_LIFETIME = timedelta(hours=1)

# A password reset token is this many random bytes, written as 64 URL-safe characters.
PASSWORD_RESET_TOKEN_BYTES = 48

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
CHANGE_PASSWORD_RATE_LIMIT = "5/minute"
FORGOT_PASSWORD_RATE_LIMIT = "3/minute"
RESET_PASSWORD_RATE_LIMIT = "5/minute"
OAUTH_START_RATE_LIMIT = "10/minute"  # the same as login: it is a login too

# Login with 42 (BE-11).
# Our own address that 42 sends the browser back to, after FRONTEND_BASE_URL. It must be
# written exactly like this in the 42 intra app settings ("Redirect URI").
OAUTH_CALLBACK_PATH = "/api/auth/oauth/42/callback"
# The frontend page that receives our tokens (in the part of the address after "#").
OAUTH_FRONTEND_PATH = "/oauth/callback"
# What we ask 42 for: "public" is the basic profile, which includes the email.
OAUTH_SCOPE = "public"
# How long a login with 42 can take, from the button to the callback.
OAUTH_STATE_LIFETIME = timedelta(minutes=10)
# The state is this many random bytes, written as 43 URL-safe characters.
OAUTH_STATE_BYTES = 32
# Where the state is kept in Redis: this prefix, then the state itself.
OAUTH_STATE_KEY_PREFIX = "oauth42:state:"
# The cookie that ties the state to the browser that clicked the button. Sent back only to
# the callback (its path) and only over HTTPS.
OAUTH_STATE_COOKIE = "oauth42_state"
# How long we wait for 42 to answer one request before giving up.
FT_REQUEST_TIMEOUT_SEC = 10
