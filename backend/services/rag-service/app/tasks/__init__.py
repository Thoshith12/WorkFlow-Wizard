"""
app.tasks — Celery background tasks for the RAG service.
"""
import asyncio
import logging
from uuid import UUID

from app.core.celery_app import celery_app
from app.pipeline.extraction.service import run_extraction_pipeline
from app.pipeline.preprocessing.service import run_preprocessing_pipeline

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.extract_document")
def extract_document_task(data_source_id_str: str) -> None:
    """Celery task wrapper for running document extraction and preprocessing."""
    logger.info("Celery task: Starting document extraction for data source %s", data_source_id_str)
    data_source_id = UUID(data_source_id_str)
    asyncio.run(run_extraction_pipeline(data_source_id))
    logger.info("Celery task: Finished document extraction for data source %s", data_source_id_str)


@celery_app.task(name="app.tasks.preprocess_document")
def preprocess_document_task(data_source_id_str: str) -> None:
    """Celery task wrapper for running preprocessing."""
    logger.info("Celery task: Starting document preprocessing for data source %s", data_source_id_str)
    data_source_id = UUID(data_source_id_str)
    asyncio.run(run_preprocessing_pipeline(data_source_id))
    logger.info("Celery task: Finished document preprocessing for data source %s", data_source_id_str)
