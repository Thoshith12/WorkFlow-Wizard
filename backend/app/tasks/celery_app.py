"""
app.tasks.celery_app — Celery application instance.

Configures Celery with Redis as the broker and result backend.
Import `celery_app` in task files to register tasks.

Usage:
    from app.tasks.celery_app import celery_app

    @celery_app.task
    def my_task(): ...
"""
from celery import Celery
from shared.config.settings import settings

celery_app = Celery(
    "backend",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.example_task"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
