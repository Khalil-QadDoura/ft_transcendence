"""The Celery app of the worker container: `celery -A app.worker.celery_app worker -B`.

Uses the same Redis broker that the API writes to (app/core/queue.py), configures late
acknowledgement so tasks are not lost on worker crash, schedules beat tasks for stuck
pending videos and worker heartbeats, and refreshes the Redis heartbeat on startup.
"""

from celery.signals import worker_ready

from app.core.config import get_settings
from app.core.queue import make_celery

_settings = get_settings()
celery_app = make_celery(_settings)
celery_app.conf.update(
    include=["app.worker.tasks.moderation"],
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Non-root container user (uid 10001) cannot write into /app; store beat state in /tmp.
    beat_schedule_filename="/tmp/celerybeat-schedule",
    beat_schedule={
        "requeue-stuck-moderation": {
            "task": "app.worker.tasks.moderation.requeue_stuck",
            "schedule": _settings.moderation_beat_interval_sec,
        },
        "worker-heartbeat": {
            "task": "app.worker.tasks.moderation.heartbeat",
            "schedule": _settings.worker_heartbeat_interval_sec,
        },
    },
)


@worker_ready.connect
def _on_worker_ready(**_kwargs) -> None:
    """Write the initial worker:heartbeat key as soon as Celery finishes booting."""
    from app.worker.tasks.moderation import write_worker_heartbeat

    settings = get_settings()
    write_worker_heartbeat(settings.redis_url, settings.worker_heartbeat_ttl_sec)
