"""
app.api.endpoints.search — Qdrant knowledge base search endpoints.

POST /api/data-sources/search
POST /api/data-sources/{data_source_id}/search

Interface Responsibilities:
  1. Validate search query parameter ranges (threshold 0.0 - 1.0, top_k >= 1).
  2. Perform Qdrant vector search across dense, sparse, or hybrid vector modes.
  3. Normalize scores to 0-1 range and apply minimum relevance threshold.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.utils.pool import get_db
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search import execute_search

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Search"])


@router.post(
    "/data-sources/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Data Connector Knowledge Base",
    description=(
        "Searches the Qdrant vector knowledge base for a specified data connector. "
        "Supports dense, sparse, and hybrid vector storage modes with scores "
        "normalized to a standard 0.0 to 1.0 range."
    ),
)
async def search_data_connector(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """
    Search Qdrant knowledge base for a data connector using JSON body:
    
    ```json
    {
      "data_connector_id": "123e4567-e89b-12d3-a456-426614174000",
      "query": "search text",
      "threshold": 0.5,
      "top_k": 5
    }
    ```
    """
    return await execute_search(
        db,
        data_connector_id=request.data_connector_id,
        query=request.query,
        threshold=request.threshold,
        top_k=request.top_k,
    )


@router.post(
    "/data-sources/{data_source_id}/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Data Connector Knowledge Base (Path ID)",
    description="Convenience path-based endpoint for searching a specific data connector.",
)
async def search_data_connector_by_path(
    data_source_id: UUID,
    query: str = Query(..., min_length=1, description="Search query string"),
    threshold: float = Query(0.0, ge=0.0, le=1.0, description="Minimum relevance score threshold (0.0 to 1.0)"),
    top_k: int = Query(5, ge=1, le=100, description="Max results limit"),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """
    Search Qdrant knowledge base for a data connector using path ID and query parameters.
    """
    return await execute_search(
        db,
        data_connector_id=data_source_id,
        query=query,
        threshold=threshold,
        top_k=top_k,
    )
