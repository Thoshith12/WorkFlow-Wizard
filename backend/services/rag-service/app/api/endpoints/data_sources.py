"""
app.api.endpoints.data_sources — Data source ingestion endpoint.

POST /api/data-sources/ingest-files

Interface & Validation Responsibilities:
  1. Validate batch request constraints (file count 1–10, file size ≤ 20 MB).
  2. Validate allowed file extensions (PDF, Word, Text).
  3. Verify data source name uniqueness.
  4. Disperse / dispatch execution task to the Ingestion Pipeline (app.pipeline.ingestion).
"""
import logging
import os
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config.settings import settings
from shared.database.utils.pool import get_db
from app.pipeline import run_ingestion_pipeline
from app.tasks import extract_document_task
from app.repositories import data_source as ds_repo
from app.schemas.data_source import IngestResponse


logger = logging.getLogger(__name__)

router = APIRouter()

# Derived constants
MAX_FILE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = 10
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}


@router.post(
    "/data-sources/ingest-files",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Data Sources"],
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

