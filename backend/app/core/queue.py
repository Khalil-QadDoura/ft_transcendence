"""The background queue: Celery messages kept in Redis.

The API only drops a message ("moderate video 12") into the queue and answers at once; the
Celery worker takes it off later and does the slow work. A letter, not a phone call.
"""

import structlog
from celery import Celery
from fastapi import Request

from app.core.config import Settings

# The task the moderation worker (BE-29) runs, under the same name as in the reference.
MODERATION_TASK = "app.worker.tasks.moderation.run_moderation_task"
# Seconds to wait for Redis to accept a connection, instead of the system's 75 or so.
CONNECT_TIMEOUT_SEC = 2

log = structlog.get_logger(__name__)


def make_celery(settings: Settings) -> Celery:
    """A Celery app that keeps its queue in Redis. Making it does not connect yet."""
    celery = Celery("wozu", broker=settings.redis_url)
    celery.conf.broker_transport_options = {"socket_connect_timeout": CONNECT_TIMEOUT_SEC}
    return celery


class TaskQueue:
    """Puts tasks on the queue, with the settings of one app."""

    def __init__(self, settings: Settings):
        self.celery = make_celery(settings)

    def moderate_video(self, video_id: int, object_key: str) -> None:
        """Ask the worker to check this video. Routes run it as a background task, after the
        answer has gone out, so a failure cannot reach the user any more: it is logged, and
        the video stays "pending" in the database until it is sent again."""
        try:
            # send_task needs only the task's name: the code of the task lives in the worker.
            self.celery.send_task(MODERATION_TASK, args=[video_id, object_key])
        except Exception:  # Redis down or unreachable: log it with the traceback
            log.exception("moderation task not queued", video_id=video_id)


def get_queue(request: Request) -> TaskQueue:
    """FastAPI dependency: this app's queue, made once in create_app()."""
    return request.app.state.queue
