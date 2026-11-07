"""The rate limiter. A route opts in with @limiter.limit("5/minute") and a `request` argument."""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip(request: Request) -> str:
    """The browser's IP. Our proxy writes it into X-Real-IP and overwrites any value the
    browser sent, and only the proxy can reach the API container. Without a proxy (tests,
    local runs) it is the IP of the direct connection."""
    return request.headers.get("x-real-ip") or get_remote_address(request)


# Counts requests per client IP, in this process's memory.
limiter = Limiter(key_func=client_ip)
