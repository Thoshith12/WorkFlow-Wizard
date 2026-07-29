"""
app.api.endpoints.data_sources — Data source ingestion & status endpoints.

POST /api/data-sources/ingest-files
GET  /api/data-sources
GET  /api/data-sources/{data_source_id}

Interface & Validation Responsibilities:
  1. Validate batch request constraints (file count 1–10, file size ≤ 20 MB).
  2. Validate allowed file extensions (PDF, Word, Text).
  3. Verify data source name uniqueness.
  4. Disperse / dispatch execution task to the Ingestion Pipeline (app.pipeline.ingestion).
  5. Expose data connector status, registry records, job details, and vector collection metadata.
"""
import logging
import os
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config.settings import settings
from shared.database.utils.pool import get_db
from app.pipeline import run_ingestion_pipeline
from app.tasks import extract_document_task
from app.repositories import data_source as ds_repo
from app.schemas.data_source import (
    IngestResponse,
    DataSourceSummary,
    DataSourceDetail,
    DocumentDetail,
    ChunkingSummary,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Data Sources"])

# Derived constants
MAX_FILE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = 10
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}


@router.post(
    "/data-sources/ingest-files",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Files",
)
async def ingest_files(
    name: str = Form(
        ...,
        description="Unique data source name.",
        examples=["project-docs"],
    ),
    description: str = Form(
        ...,
        description="Human-readable data source description.",
        examples=["Technical documentation for the project"],
    ),
    files: List[UploadFile] = File(
        ...,
        description=f"1–{MAX_FILES} files (PDF, Word, Text), each ≤ {settings.MAX_FILE_SIZE_MB} MB.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest files into the RAG pipeline.

    Supported file formats:
    - **PDF**: `.pdf`
    - **Word**: `.doc`, `.docx`
    - **Text**: `.txt`

    Validates the request interface and disperses execution to the core Ingestion Pipeline.
    """

    # ── 1. Validate file count ────────────────────────────────────────────────
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file is required.",
        )
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_FILES} files allowed per request. Received {len(files)}.",
        )

    # ── 2. Validate file format and file size limit ───────────────────────────
    file_contents: List[dict] = []
    for f in files:
        filename = f.filename or "unnamed"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unsupported file type for '{filename}'. "
                    f"Supported file formats are PDF (.pdf), Word (.doc, .docx), and Text (.txt)."
                ),
            )

        content = await f.read()
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"File '{filename}' exceeds the {settings.MAX_FILE_SIZE_MB} MB limit "
                    f"({len(content) / (1024 * 1024):.1f} MB)."
                ),
            )

        file_contents.append({
            "filename": filename,
            "content": content,
            "content_type": f.content_type or "application/octet-stream",
            "size": len(content),
        })

    # ── 3. Validate uniqueness of data source name ────────────────────────────
    existing = await ds_repo.get_data_source_by_name(db, name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Data source with name '{name}' already exists (id={existing.id}).",
        )

    # ── 4. Disperse execution task to Ingestion Pipeline ──────────────────────
    logger.info(
        "API Request validated for '%s'. Dispersing task to Ingestion Pipeline...", name
    )
    res = await run_ingestion_pipeline(
        db,
        name=name,
        description=description,
        file_contents=file_contents,
    )
    # Commit early so records are visible to the background task
    await db.commit()
    extract_document_task.delay(str(res.data_source_id))
    return res


@router.get(
    "/data-sources",
    response_model=List[DataSourceSummary],
    status_code=status.HTTP_200_OK,
    summary="List Data Connectors",
    description="List all data connectors with top-level status, document counts, and vector collections.",
)
async def list_data_sources(
    db: AsyncSession = Depends(get_db),
) -> List[DataSourceSummary]:
    """Retrieve summary list of all registered data connectors."""
    data_sources = await ds_repo.get_all_data_sources(db)
    summaries: List[DataSourceSummary] = []

    for ds in data_sources:
        chunk_info = await ds_repo.get_chunk_summary_for_data_source(db, ds.id)
        summaries.append(
            DataSourceSummary(
                data_source_id=ds.id,
                name=ds.name,
                description=ds.description,
                status=ds.status,
                error=ds.error,
                document_count=len(ds.documents) if ds.documents else 0,
                total_chunks=chunk_info["total_chunks"],
                vector_collections=chunk_info["vector_collections"],
                created_at=ds.created_at,
                updated_at=ds.updated_at,
            )
        )

    return summaries


@router.get(
    "/data-sources/{data_source_id}",
    response_model=DataSourceDetail,
    status_code=status.HTTP_200_OK,
    summary="Get Data Connector Registry Details",
    description=(
        "Get comprehensive details for a specific data connector, including "
        "document status, chunking job details, configs, errors, and Qdrant collections."
    ),
)
async def get_data_source_detail(
    data_source_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> DataSourceDetail:
    """Retrieve full registry details for a data connector by UUID."""
    ds = await ds_repo.get_data_source_by_id(db, data_source_id)
    if ds is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data connector '{data_source_id}' not found.",
        )

    # Document details list
    doc_details: List[DocumentDetail] = []
    if ds.documents:
        for doc in ds.documents:
            cfg = doc.config or {}
            doc_details.append(
                DocumentDetail(
                    document_id=doc.id,
                    file_name=doc.file_name,
                    pipeline_status=doc.pipeline_status,
                    storage_path=cfg.get("storage_path"),
                    file_size_bytes=cfg.get("file_size_bytes"),
                    content_type=cfg.get("content_type"),
                    language_detected=doc.language_detected or [],
                    page_count=doc.page_count,
                    error=doc.error,
                    created_at=doc.created_at,
                )
            )

    # Chunking & vector store summary
    chunk_info = await ds_repo.get_chunk_summary_for_data_source(db, ds.id)
    chunking_summary = ChunkingSummary(
        job_id=chunk_info["job_id"],
        total_chunks=chunk_info["total_chunks"],
        chunk_status_counts=chunk_info["chunk_status_counts"],
        vector_collections=chunk_info["vector_collections"],
        embedding_models=chunk_info["embedding_models"],
        embedding_modes=chunk_info["embedding_modes"],
    )

    return DataSourceDetail(
        data_source_id=ds.id,
        name=ds.name,
        description=ds.description,
        status=ds.status,
        error=ds.error,
        config=ds.config or {},
        created_at=ds.created_at,
        updated_at=ds.updated_at,
        document_count=len(doc_details),
        documents=doc_details,
        chunking_info=chunking_summary,
    )
