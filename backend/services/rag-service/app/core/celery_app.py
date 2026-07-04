"""
app.core.celery_app — Celery application instance for RAG service.

Configures Celery with Redis as the broker and result backend.
Imports are included automatically from app.tasks.
"""
from celery import Celery
from shared.config.settings import settings

celery_app = Celery(
    "rag-service",
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
)

from celery.signals import setup_logging
from shared.logging.setup import configure_logging

@setup_logging.connect
def on_setup_logging(**kwargs):
    configure_logging(service_name="rag-celery-worker", level=settings.LOG_LEVEL)
