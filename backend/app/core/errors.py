"""One error shape for the whole API: {"error": {"code": "<status>", "detail": ...}}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException


def error_response(
    status: int, detail: object, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": str(status), "detail": detail}},
        headers=headers,
    )


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    """Errors raised on purpose (HTTPException), plus 404 and 405 from the router."""
    return error_response(exc.status_code, exc.detail, exc.headers)


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Bad input: report only the first failing field, e.g. "body → email: Field required"."""
    first = exc.errors()[0]
    where = " → ".join(str(part) for part in first["loc"])
    return error_response(422, f"{where}: {first['msg']}")


async def rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return error_response(429, f"Rate limit exceeded: {exc.detail}")


async def server_error(request: Request, exc: Exception) -> JSONResponse:
    """A bug: the server log keeps the traceback, the client gets no internals."""
    return error_response(500, "Internal server error")


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(RateLimitExceeded, rate_limited)
    app.add_exception_handler(Exception, server_error)
