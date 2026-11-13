"""Prometheus metrics setup: HTTP instrumentation and custom WebSocket gauge (BE-30)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import CollectorRegistry, Gauge
from prometheus_fastapi_instrumentator import Instrumentator


def setup_metrics(app: FastAPI) -> None:
    """Attach HTTP Prometheus instrumentation and expose /metrics outside OpenAPI.

    Uses a per-app CollectorRegistry so repeated create_app() calls across tests remain isolated
    and never collide on duplicate metric registration.
    """
    registry = CollectorRegistry()
    app.state.metrics_registry = registry
    app.state.ws_connections_gauge = Gauge(
        "ws_connections",
        "Number of currently open WebSocket connections",
        registry=registry,
    )
    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics"],
        registry=registry,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@asynccontextmanager
async def track_ws_connection(app: FastAPI) -> AsyncIterator[None]:
    """Increment and reliably decrement the open WebSocket connections gauge for one socket."""
    gauge: Gauge | None = getattr(app.state, "ws_connections_gauge", None)
    if gauge is not None:
        gauge.inc()
    try:
        yield
    finally:
        if gauge is not None:
            gauge.dec()
