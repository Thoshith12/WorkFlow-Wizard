"""
app.schemas.data_source — Pydantic request / response schemas for data ingestion.

Kept separate from ORM models to maintain a clean boundary between
the API contract and the persistence layer.
"""
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Response sub-models ───────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    """Single document in the ingestion response."""
    document_id: UUID = Field(..., description="Unique document identifier.")
    file_name: str = Field(..., description="Original uploaded file name.")
    pipeline_status: str = Field(..., description="Document processing status.")
    storage_path: str = Field(
        ..., description="Storage path in object storage."
    )


    model_config = {"from_attributes": True}


# ── Ingest response ──────────────────────────────────────────────────────────

class IngestResponse(BaseModel):
    """Response returned after a successful data source ingestion."""
    data_source_id: UUID = Field(
        ..., description="Created data source identifier."
    )
    name: str = Field(..., description="Data source name.")
    description: str = Field(..., description="Data source description.")
    document_count: int = Field(
        ..., description="Number of documents ingested."
    )
    documents: List[DocumentOut] = Field(
        ..., description="Details of each ingested document."
    )

    model_config = {"from_attributes": True}
