"""The rate limiter. A route opts in with @limiter.limit("5/minute") and a `request` argument."""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Counts requests per client IP, in this process's memory. Behind the proxy, uvicorn's
# --proxy-headers option turns X-Forwarded-For into the client IP.
limiter = Limiter(key_func=get_remote_address)
