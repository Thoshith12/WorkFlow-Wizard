"""
app.core.celery_app — Celery application instance for Tools service.

Configures Celery with Redis as the broker and result backend.
Includes sandbox reaper in the beat schedule.
"""
from celery import Celery
from shared.config.settings import settings
from app.config.tool_settings import tool_settings

celery_app = Celery(
    "tools-service",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "sandbox-reaper": {
            "task": "app.tasks.sandbox_reaper.reap_idle_containers",
            "schedule": tool_settings.sandbox.reaper_interval_seconds,
        },
    },
)

from celery.signals import setup_logging
from shared.logging.setup import configure_logging


@setup_logging.connect
def on_setup_logging(**kwargs):
    configure_logging(service_name="tools-celery-worker", level=settings.LOG_LEVEL)
