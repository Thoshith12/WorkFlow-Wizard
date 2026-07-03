"""
app.pipeline.ingestion.service — Data Ingestion Pipeline.

Encapsulates all execution business logic for data ingestion:
  1. Creating data_source_registry record in PostgreSQL.
  2. Uploading binary file streams to MinIO object storage.
  3. Creating document_registry records in PostgreSQL.

Decoupled from FastAPI endpoint routing and request validation.
"""
import logging
from typing import Any, Dict, List

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import data_source as ds_repo
from app.repositories import document as doc_repo
from app.schemas.data_source import DocumentOut, IngestResponse
from app.services.minio import minio_client

logger = logging.getLogger(__name__)


async def run_ingestion_pipeline(
    db: AsyncSession,
    *,
    name: str,
    description: str,
    file_contents: List[Dict[str, Any]],
) -> IngestResponse:
    """
    Execute the ingestion pipeline for a validated set of files.

    Args:
        db:            Active async database session.
        name:          Unique data source name.
        description:   Data source description.
        file_contents: List of dicts containing filename, content, content_type, size.

    Returns:
        IngestResponse containing created data source ID and document details.
    """
    # ── 1. Create DataSource registry row ─────────────────────────────────────
    data_source = await ds_repo.create_data_source(
        db,
        name=name,
        description=description,
        config={"file_count": len(file_contents)},
    )
    logger.info(
        "Ingestion Pipeline: DataSource created id=%s name=%r files=%d",
        data_source.id, name, len(file_contents),
    )

    # ── 2. Upload files to MinIO + create Document registry rows ──────────────
    doc_responses: List[DocumentOut] = []
    for fc in file_contents:
        try:
            storage_path = await minio_client.upload(
                data_source_id=data_source.id,
                filename=fc["filename"],
                content=fc["content"],
                content_type=fc["content_type"],
            )
        except Exception as exc:
            logger.error(
                "Ingestion Pipeline: MinIO upload failed for '%s': %s", fc["filename"], exc
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to upload '{fc['filename']}' to object storage: {exc}",
            )

        doc = await doc_repo.create_document(
            db,
            data_source_id=data_source.id,
            file_name=fc["filename"],
            pipeline_status="stored",
            config={
                "storage_path": storage_path,
                "content_type": fc["content_type"],
                "file_size_bytes": fc["size"],
            },
        )

        doc_responses.append(
            DocumentOut(
                document_id=doc.id,
                file_name=doc.file_name,
                pipeline_status=doc.pipeline_status,
                storage_path=storage_path,
            )
        )

    logger.info(
        "Ingestion Pipeline complete: ds_id=%s docs=%d", data_source.id, len(doc_responses)
    )

    return IngestResponse(
        data_source_id=data_source.id,
        name=data_source.name,
        description=data_source.description,
        document_count=len(doc_responses),
        documents=doc_responses,
    )
