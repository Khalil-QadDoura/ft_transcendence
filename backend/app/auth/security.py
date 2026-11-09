"""Password hashing (Argon2id) and the signed tokens (JWT, HS256). No database, no HTTP."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Argon2id with the library's defaults (the RFC 9106 settings: 64 MiB of memory, 3 passes,
# 4 lanes). Each hash gets its own random salt, kept inside the hash string itself.
_hasher = PasswordHasher()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Returns "$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>": settings, salt and hash."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """True when the password matches the stored hash.

    With no hash (no such account) it still runs Argon2 once, so that answer takes as long
    as a wrong password: nobody can time the answer to learn which emails have an account.
    """
    if password_hash is None:
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_token(
    secret: str, user_id: int, scope: str, lifetime: timedelta, **extra: object
) -> tuple[str, dict]:
    """A signed token for one user. Returns the token and its claims (the data inside it)."""
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),  # who: the user id (a JWT subject is always a string)
        "scope": scope,  # what for: access, refresh or email_verify
        "jti": uuid.uuid4().hex,  # this token's own unique id
        "iat": now,  # issued at
        "exp": now + lifetime,  # expires at
        **extra,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM), claims


def read_token(secret: str, token: str, scope: str) -> dict:
    """The claims of a token we signed, not expired, made for `scope`.

    Anything else raises jwt.InvalidTokenError: a changed or foreign token (bad signature),
    an expired one, a missing claim, or another kind of token (wrong scope).
    """
    claims = jwt.decode(
        token, secret, algorithms=[ALGORITHM], options={"require": ["sub", "scope", "jti", "exp"]}
    )
    if claims["scope"] != scope:
        raise jwt.InvalidTokenError(f"wrong scope, expected {scope}")
    return claims
