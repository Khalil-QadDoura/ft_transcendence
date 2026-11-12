"""App factory: builds the FastAPI app from settings, middleware, error handlers and routers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, Depends, FastAPI

from app.auth import routes as auth
from app.companies import routes as companies
from app.conversations import routes as conversations
from app.core.config import Settings, get_settings
from app.core.errors import add_error_handlers
from app.core.internal import require_internal_key
from app.core.limiter import limiter
from app.core.logging import configure_logging
from app.core.queue import TaskQueue
from app.core.redis_client import setup_redis
from app.core.request_id import request_id_middleware
from app.core.storage import Storage
from app.db.session import setup_database
from app.health import routes as health
from app.jobs import routes as jobs
from app.media import routes as media
from app.realtime import routes as realtime
from app.users import routes as users

log = structlog.get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Code before `yield` runs once at start-up, code after it once at shutdown."""
    log.info("startup", env=app.state.settings.env)
    yield
    await app.state.engine.dispose()  # close this app's pooled database connections
    await app.state.redis.aclose()  # and its Redis connections
    log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="WOZU Web API",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs" if settings.env == "dev" else None,
        # Swagger's helper page for its "Authorize" button; it exists only with the docs.
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.limiter = limiter  # slowapi looks for the limiter here
    setup_database(app, settings)  # this app's engine, from this app's settings
    setup_redis(app, settings)  # this app's Redis client, the same way
    app.state.storage = Storage(settings)  # MinIO, where the videos are kept
    app.state.queue = TaskQueue(settings)  # Redis, the queue of the Celery worker

    add_error_handlers(app)
    app.middleware("http")(request_id_middleware)

    # Public API: every router goes under /api. WebSockets live under /ws.
    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(companies.router)
    api.include_router(conversations.router)
    api.include_router(jobs.router)
    api.include_router(realtime.router)  # POST /api/ws/ticket
    api.include_router(media.router)
    app.include_router(api)
    app.include_router(realtime.socket_router)  # the WebSocket at /ws

    # Internal routes: left out of the OpenAPI spec and locked by X-Internal-Key.
    internal = APIRouter(
        prefix="/_internal",
        dependencies=[Depends(require_internal_key)],
        include_in_schema=False,
    )
    internal.include_router(health.internal_router)
    app.include_router(internal)
    return app


# What uvicorn serves: `uvicorn app.main:app`.
app = create_app()
