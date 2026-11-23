"""The rate limiter (numbers in core/limits.py). Three kinds of limits use it:

- Login and sign-up count per client IP: @limiter.limit(LOGIN_RATE_LIMIT) on the route, which
  then needs a `request` argument (slowapi).
- Every write under /api counts per user, or per IP when nobody is logged in: limit_writes,
  which main.py puts on the /api router, so a new write route is covered without a word.
- The game chat counts each player's lines with used_up (game/chat.py).

The counts live in this process's memory. The API is one process (docker-entrypoint.sh runs
one uvicorn worker), so every request meets the same counts. They start from zero on restart.
"""

import math
import time

import jwt
from fastapi import HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param
from limits import RateLimitItem, parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.constants import ACCESS_SCOPE
from app.auth.security import read_token
from app.core.limits import ROUTE_RATE_LIMITS, WRITE_RATE_LIMIT

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def client_ip(request: Request) -> str:
    """The browser's IP. Our proxy writes it into X-Real-IP and overwrites any value the
    browser sent, and only the proxy can reach the API container. Without a proxy (tests,
    local runs) it is the IP of the direct connection."""
    return request.headers.get("x-real-ip") or get_remote_address(request)


# slowapi's limiter: the @limiter.limit decorator (per client IP), and the counts of every
# limit above, in this process's memory (limiter.limiter counts them).
limiter = Limiter(key_func=client_ip)


def client_key(request: Request) -> str:
    """Whose count a write goes to: "user:<id>" for a valid access token of ours, else
    "ip:<address>". Only the signature and the expiry are checked here (no database): a
    made-up or expired token counts for its IP, so inventing user ids gives nobody a new count.
    The route itself still checks the user as always (401)."""
    scheme, token = get_authorization_scheme_param(request.headers.get("authorization"))
    if scheme.lower() == "bearer" and token:
        try:
            claims = read_token(request.app.state.settings.jwt_secret, token, ACCESS_SCOPE)
        except jwt.InvalidTokenError:
            pass
        else:
            return f"user:{claims['sub']}"
    return f"ip:{client_ip(request)}"


def used_up(item: RateLimitItem, *identifiers: str) -> bool:
    """Count one request for these identifiers; True once their limit is used up."""
    return not limiter.limiter.hit(item, *identifiers)


def seconds_to_wait(item: RateLimitItem, *identifiers: str) -> int:
    """How long until this count starts again, in whole seconds (the Retry-After header)."""
    reset_at = limiter.limiter.get_window_stats(item, *identifiers).reset_time
    return max(1, math.ceil(reset_at - time.time()))


async def limit_writes(request: Request) -> None:
    """Every POST, PUT, PATCH and DELETE under /api: 429 (the standard error body) once the
    route's limit is used up. Reads (GET) are never counted. Runs before the route's own
    checks, so even a request that would fail (401, 422) counts."""
    if request.method not in WRITE_METHODS:
        return
    # The route's path as its router writes it, without /api, e.g.
    # "POST /friends/requests/{friendship_id}/accept": one count for the route, whatever the id.
    route = f"{request.method} {request.scope['route'].path}"
    item = parse(ROUTE_RATE_LIMITS.get(route, WRITE_RATE_LIMIT))
    identifiers = ("write", route, client_key(request))
    if used_up(item, *identifiers):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {item}",
            headers={"Retry-After": str(seconds_to_wait(item, *identifiers))},
        )
