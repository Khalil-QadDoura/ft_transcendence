"""The Celery app of the worker container: `celery -A app.worker.celery_app worker -B`.

The same queue the API writes to (app/core/queue.py). BE-07 only puts moderation tasks on it;
the moderation card (BE-29) adds the task itself, which takes them off and checks each video.
"""

from app.core.config import get_settings
from app.core.queue import make_celery

celery_app = make_celery(get_settings())
