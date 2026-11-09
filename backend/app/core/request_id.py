"""Give every request an id, write it into each log line of that request and into the response."""

import time
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.core.errors import server_error

HEADER = "x-request-id"
log = structlog.get_logger("app.request")


async def request_id_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    # Keep the id the proxy sent, so its logs and ours match; otherwise make a new one.
    request_id = request.headers.get(HEADER, "")
    if not request_id or len(request_id) > 64:
        request_id = uuid.uuid4().hex
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        # A bug in a route. The traceback goes to our log only; the client gets the safe
        # 500 body, and that response still gets its id and its "request" line below.
        log.exception("unhandled error")
        response = await server_error(request, exc)
    response.headers[HEADER] = request_id
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return response
