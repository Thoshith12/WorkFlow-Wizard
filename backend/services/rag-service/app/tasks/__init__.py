"""
app.tasks — Celery task registry for the RAG service.

Importing this package registers all task modules with the Celery app so they
are discoverable by workers. Add new task modules here as additional pipelines
(chunking, embedding, ingestion, etc.) are introduced.
"""
from app.tasks.extraction import extract_document_orchestrator_task as extract_document_task
from app.tasks import preprocessing  # noqa: F401 — registers preprocessing tasks
from app.tasks import chunking       # noqa: F401 — registers chunking + embedding tasks

__all__ = [
    "extract_document_task",
]

