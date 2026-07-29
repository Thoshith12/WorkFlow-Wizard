"""
app.schemas.search — Request and response schemas for Qdrant knowledge base search.

Provides validation and serialization for vector search queries across
data connectors in dense, sparse, or hybrid mode with normalized scores.
"""
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """
    Search request for a data connector's vector knowledge base in Qdrant.
    """
    data_connector_id: UUID = Field(
        ...,
        description="Unique identifier (UUID) of the data connector / knowledge base.",
        examples=["123e4567-e89b-12d3-a456-426614174000"],
    )
    query: str = Field(
        ...,
        min_length=1,
        description="Text query string to search for.",
        examples=["What is the architectural overview of the project?"],
    )
    threshold: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum similarity score threshold (0.0 to 1.0). "
            "Scores across dense, sparse, and hybrid modes are normalized to 0-1."
        ),
        examples=[0.5],
    )
    top_k: int = Field(
        5,
        ge=1,
        le=100,
        description="Maximum number of search results to return.",
        examples=[5],
    )


class SearchResultItem(BaseModel):
    """Individual chunk match item in search results."""
    chunk_id: UUID = Field(..., description="Unique chunk UUID identifier.")
    document_id: Optional[UUID] = Field(None, description="Source document UUID identifier.")
    chunk_text: str = Field(..., description="Text content of the matched chunk.")
    chunk_index: int = Field(..., description="0-based index of the chunk.")
    page_number: Optional[int] = Field(None, description="Source page number, if applicable.")
    score: float = Field(
        ...,
        description="Normalized similarity/relevance score scaled cleanly between 0.0 and 1.0.",
    )
    raw_score: float = Field(
        ...,
        description="Original raw score returned by Qdrant.",
    )
    embedding_mode: str = Field(
        ...,
        description="Vector storage mode used: dense, hybrid, or sparse.",
    )
    embedding_model: str = Field(
        ...,
        description="HuggingFace model name used to embed this chunk.",
    )

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    """Response returned by the Qdrant knowledge base search endpoint."""
    data_connector_id: UUID = Field(..., description="Data connector identifier.")
    query: str = Field(..., description="Original text query.")
    top_k: int = Field(..., description="Requested top_k parameter.")
    threshold: float = Field(..., description="Requested score threshold.")
    results_count: int = Field(..., description="Number of results matching criteria.")
    results: List[SearchResultItem] = Field(..., description="List of matched search result items.")

    model_config = {"from_attributes": True}
