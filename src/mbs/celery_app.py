import os

from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "mbs",
    broker=redis_url,
    backend=redis_url,
    include=["mbs.receipts.tasks"],
)
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.beat_schedule = {
    "dispatch-pending-receipt-uploads": {
        "task": "mbs.receipts.dispatch_pending_uploads",
        "schedule": 10.0,
    }
}
