"""
app.api.endpoints.chunking — Chunking & embedding pipeline endpoint.

POST /api/data-sources/{data_source_id}/chunk

Responsibilities:
  1. Validate the data source exists.
  2. Guard: all documents for the data source must have
     pipeline_status = "preprocessing completed" before chunking is allowed.
  3. Validate all requested embedding_models exist in the registry.
  4. Compute the Qdrant collection name.
  5. Dispatch chunking_orchestrator_task via Celery.
  6. Return ChunkingResponse immediately (202 Accepted — async job).
"""
import json
import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.utils.pool import get_db
from app.models.data_source import DataSource
from app.models.document import Document
from app.schemas.chunking import ChunkingRequest, ChunkingResponse
from app.pipeline.chunking.embedding_adapter import (
    get_model_config,
    is_model_known,
)
from app.tasks.chunking import chunking_orchestrator_task

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chunking"])


@router.post(
    "/data-sources/{data_source_id}/chunk",
    response_model=ChunkingResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate chunking and embedding for a data connector",
    description=(
        "Starts the asynchronous chunking + embedding pipeline for a data connector. "
        "All documents belonging to the data source must have completed preprocessing "
        "before this endpoint can be called. Returns immediately with status 'initiated'."
    ),
)
async def initiate_chunking(
    data_source_id: UUID,
    request: ChunkingRequest,
    db: AsyncSession = Depends(get_db),
) -> ChunkingResponse:
    """
    POST /api/data-sources/{data_source_id}/chunk

    Guards:
      - 404 if data_source_id does not exist.
      - 409 if any document is not yet at 'preprocessing completed'.
      - 400 if any embedding_model name is not in the registry.

    On success:
      - Dispatches chunking_orchestrator_task.delay(...) via Celery.
      - Returns ChunkingResponse with status='initiated'.
    """
    # ── 1. Validate data source exists ────────────────────────────────────────
    ds_result = await db.execute(
        select(DataSource).where(DataSource.id == data_source_id)
    )
    data_source = ds_result.scalar_one_or_none()
    if data_source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data source '{data_source_id}' not found.",
        )

    # ── 2. Guard: all documents must be preprocessed ──────────────────────────
    docs_result = await db.execute(
        select(Document).where(Document.data_source_id == data_source_id)
    )
    all_docs: List[Document] = list(docs_result.scalars().all())

    if not all_docs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Data source '{data_source_id}' has no documents. "
                "Ingest files and wait for extraction + preprocessing to complete first."
            ),
        )

    pending = [
        str(doc.id)
        for doc in all_docs
        if doc.pipeline_status != "preprocessing completed"
    ]
    if pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Not all documents have completed preprocessing. "
                f"Pending document IDs ({len(pending)}): {pending}. "
                "All documents must reach 'preprocessing completed' before chunking."
            ),
        )

    # ── 3. Validate embedding models ──────────────────────────────────────────
    unknown_models = [m for m in request.embedding_models if not is_model_known(m)]
    if unknown_models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown embedding model(s): {unknown_models}. "
                "Add them to app/config/embedding_models.yaml first."
            ),
        )

    # ── 4. Compute Qdrant collection name ─────────────────────────────────────
    primary_model = request.embedding_models[0]
    model_cfg = get_model_config(primary_model)
    short_name = model_cfg["short_name"]
    dims = model_cfg["dimensions"]
    vector_collection = f"{data_source_id}_{short_name}_{dims}"

    # ── 5. Build config payload for Celery tasks ──────────────────────────────
    config_dict = {
        "chunking_strategy":  request.chunking_strategy.value,
        "embedding_mode":     request.embedding_mode.value,
        "embedding_models":   request.embedding_models,
        "chunks_per_batch":   request.chunks_per_batch,
        "pages_per_batch":    request.pages_per_batch,
        "vector_collection":  vector_collection,
        # Per-strategy configs
        "fixed_config":        request.fixed_config.model_dump(),
        "recursive_config":    request.recursive_config.model_dump(),
        "semantic_config":     request.semantic_config.model_dump(),
        "parent_child_config": request.parent_child_config.model_dump(),
        "agentic_config":      request.agentic_config.model_dump(),
    }

    # ── 6. Dispatch Celery task ───────────────────────────────────────────────
    chunking_orchestrator_task.delay(
        data_source_id_str=str(data_source_id),
        config_json=json.dumps(config_dict),
    )

    logger.info(
        "Chunking initiated",
        extra={
            "event":             "chunking_initiated",
            "data_source_id":    str(data_source_id),
            "strategy":          request.chunking_strategy.value,
            "embedding_mode":    request.embedding_mode.value,
            "embedding_models":  request.embedding_models,
            "vector_collection": vector_collection,
            "doc_count":         len(all_docs),
        },
    )

    return ChunkingResponse(
        data_source_id=data_source_id,
        job_id=data_source_id,
        status="initiated",
        chunking_strategy=request.chunking_strategy.value,
        embedding_mode=request.embedding_mode.value,
        embedding_models=request.embedding_models,
        vector_collection=vector_collection,
        message=(
            f"Chunking job initiated for {len(all_docs)} document(s) using "
            f"'{request.chunking_strategy.value}' strategy and "
            f"'{request.embedding_mode.value}' embedding mode. "
            f"Vectors will be stored in Qdrant collection '{vector_collection}'."
        ),
    )
