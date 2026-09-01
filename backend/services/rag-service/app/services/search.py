"""
app.services.search — Core execution logic for searching Qdrant knowledge bases.

Encapsulates:
  1. Data Connector lookup & chunk registry metadata resolution.
  2. Embedding query string with exact model & dimensions configured for the connector.
  3. Qdrant vector search across dense, sparse, and hybrid modes.
  4. Score normalization to a 0.0 - 1.0 scale and threshold filtering.
"""
import math
import logging
from typing import List, Dict, Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from qdrant_client import QdrantClient

from shared.config.settings import settings
from app.models.data_source import DataSource
from app.models.chunk import Chunk
from app.models.enums.chunking import ChunkStatus, EmbeddingMode
from app.pipeline.chunking.embedding_adapter import embed_texts, get_model_config
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem

logger = logging.getLogger(__name__)


def normalize_score(raw_score: float, embedding_mode: str) -> float:
    """
    Normalize Qdrant raw search scores to a uniform 0.0 – 1.0 scale.

    - Cosine similarity (dense): raw_score is in [-1.0, 1.0].
      Since normalized embeddings yield scores in [0.0, 1.0] for relevant text,
      we clamp to [0.0, 1.0].
    - BM25 / Sparse: raw_score is in [0, +inf). We apply standard saturation
      scaling: score = raw_score / (1.0 + raw_score).
    - Hybrid (RRF / combined): clamp to [0.0, 1.0].
    """
    if embedding_mode == EmbeddingMode.SPARSE.value:
        if raw_score <= 0.0:
            return 0.0
        return round(raw_score / (1.0 + raw_score), 4)

    # Dense or Hybrid (cosine metric)
    return round(max(0.0, min(1.0, float(raw_score))), 4)


async def execute_search(
    db: AsyncSession,
    *,
    data_connector_id: UUID,
    query: str,
    threshold: float = 0.0,
    top_k: int = 5,
) -> SearchResponse:
    """
    Search a data connector's Qdrant vector collection.

    Steps:
      1. Verify DataSource exists in PostgreSQL.
      2. Fetch chunk metadata (embedding_model, vector_collection, config) from chunk_registry.
      3. Verify model config & dims in embedding_models registry.
      4. Embed user query using the connector's embedding model.
      5. Search Qdrant collection using QdrantClient search_points API.
      6. Normalize scores to 0-1 and apply threshold filtering.

    Returns:
      SearchResponse with matched results.
    """
    # ── 1. Validate DataSource exists ─────────────────────────────────────────
    ds_result = await db.execute(
        select(DataSource).where(DataSource.id == data_connector_id)
    )
    data_source = ds_result.scalar_one_or_none()
    if data_source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data connector '{data_connector_id}' not found.",
        )

    # ── 2. Retrieve chunk metadata for this data connector ───────────────────
    chunk_result = await db.execute(
        select(Chunk)
        .where(
            Chunk.data_source_id == data_connector_id,
            Chunk.status == ChunkStatus.VECTOR_STORE_SUCCESSFUL.value,
        )
        .limit(1)
    )
    sample_chunk = chunk_result.scalar_one_or_none()

    if sample_chunk is None:
        # Fall back to checking any chunk row for vector_collection
        any_chunk_res = await db.execute(
            select(Chunk)
            .where(Chunk.data_source_id == data_connector_id)
            .limit(1)
        )
        sample_chunk = any_chunk_res.scalar_one_or_none()

    if sample_chunk is None or not sample_chunk.vector_collection:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Data connector '{data_connector_id}' has not completed chunking and vector storage. "
                f"Current status: '{data_source.status}'."
            ),
        )

    vector_collection = sample_chunk.vector_collection
    chunk_cfg = sample_chunk.config or {}
    embedding_mode = chunk_cfg.get("embedding_mode", EmbeddingMode.DENSE.value)
    
    # Determine embedding model used
    embedding_model = sample_chunk.embedding_model
    if not embedding_model:
        models_list = chunk_cfg.get("embedding_models", [])
        embedding_model = models_list[0] if models_list else "sentence-transformers/all-MiniLM-L6-v2"

    # ── 3. Validate embedding model config & dimensions ───────────────────────
    try:
        model_cfg = get_model_config(embedding_model)
        dims = model_cfg["dimensions"]
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Embedding model '{embedding_model}' used by connector is not in registry.",
        )

    logger.info(
        "Search request for connector=%s collection=%s model=%s (dims=%d, mode=%s)",
        data_connector_id, vector_collection, embedding_model, dims, embedding_mode,
    )

    # ── 4. Embed query text ───────────────────────────────────────────────────
    try:
        query_vectors = embed_texts([query], model_name=embedding_model, is_query=True)
        query_vector = query_vectors[0]
    except Exception as exc:
        logger.error("Failed to generate query embedding for '%s': %s", embedding_model, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate query embedding: {exc}",
        )

    # ── 5. Execute Qdrant vector search ──────────────────────────────────────────
    try:
        qdrant = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            check_compatibility=False,
        )

        # Check if collection exists
        existing_cols = [c.name for c in qdrant.get_collections().collections]
        if vector_collection not in existing_cols:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Qdrant collection '{vector_collection}' does not exist.",
            )

        # Fetch extra items so threshold filtering doesn't drop below top_k
        fetch_limit = max(top_k * 3, 20)

        vec_using = "dense" if embedding_mode in (EmbeddingMode.DENSE.value, EmbeddingMode.HYBRID.value) else None

        if hasattr(qdrant, "query_points"):
            res = qdrant.query_points(
                collection_name=vector_collection,
                query=query_vector,
                using=vec_using,
                limit=fetch_limit,
                with_payload=True,
            )
            search_results = res.points
        elif hasattr(qdrant, "search"):
            search_results = qdrant.search(
                collection_name=vector_collection,
                query_vector=("dense", query_vector) if vec_using else query_vector,
                limit=fetch_limit,
            )
        else:
            search_results = []

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Qdrant search failed for collection '%s': %s", vector_collection, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Qdrant search query failed: {exc}",
        )

    # ── 6. Normalize scores & filter by threshold ─────────────────────────────
    result_items: List[SearchResultItem] = []

    for point in search_results:
        payload = point.payload or {}
        raw_score = float(point.score)
        norm_score = normalize_score(raw_score, embedding_mode)

        if norm_score < threshold:
            continue

        chunk_id_str = str(point.id)
        doc_id_str = payload.get("document_id")

        result_items.append(
            SearchResultItem(
                chunk_id=UUID(chunk_id_str) if chunk_id_str else sample_chunk.id,
                document_id=UUID(doc_id_str) if doc_id_str else sample_chunk.document_id,
                chunk_text=payload.get("chunk_text", ""),
                chunk_index=payload.get("chunk_index", 0),
                page_number=payload.get("page_number"),
                score=norm_score,
                raw_score=round(raw_score, 4),
                embedding_mode=embedding_mode,
                embedding_model=payload.get("embedding_model", embedding_model),
            )
        )

    # Cap to requested top_k
    final_results = result_items[:top_k]

    return SearchResponse(
        data_connector_id=data_connector_id,
        query=query,
        top_k=top_k,
        threshold=threshold,
        results_count=len(final_results),
        results=final_results,
    )
