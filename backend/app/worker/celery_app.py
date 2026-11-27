"""The Celery app of the worker container: `celery -A app.worker.celery_app worker -B`.

Uses the same Redis broker that the API writes to (app/core/queue.py), configures late
acknowledgement so tasks are not lost on worker crash, schedules beat tasks for stuck
pending videos and worker heartbeats, and refreshes the Redis heartbeat on startup. Once a day
the beat also anonymises the accounts deleted more than 30 days ago (BE-34).
"""

from celery.schedules import crontab
from celery.signals import setup_logging, worker_ready

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.queue import make_celery
from app.users.constants import ANONYMISE_HOUR_UTC

_settings = get_settings()
celery_app = make_celery(_settings)
celery_app.conf.update(
    include=["app.worker.tasks.moderation", "app.worker.tasks.anonymise"],
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_hijack_root_logger=False,
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
        # Every day at a fixed hour, not every 24 hours: a restarted worker forgets when the
        # last run was, and a run that is missed is caught up the next day.
        "anonymise-deleted-accounts": {
            "task": "app.worker.tasks.anonymise.anonymise_deleted",
            "schedule": crontab(hour=ANONYMISE_HOUR_UTC, minute=0),
        },
    },
)


@setup_logging.connect
def _on_setup_logging(**_kwargs) -> None:
    """Use the API's structured JSON log format in the Celery worker/beat process."""
    configure_logging(get_settings().log_level)


@worker_ready.connect
def _on_worker_ready(**_kwargs) -> None:
    """Write the initial worker:heartbeat key as soon as Celery finishes booting."""
    from app.worker.tasks.moderation import write_worker_heartbeat

    settings = get_settings()
    write_worker_heartbeat(settings.redis_url, settings.worker_heartbeat_ttl_sec)
