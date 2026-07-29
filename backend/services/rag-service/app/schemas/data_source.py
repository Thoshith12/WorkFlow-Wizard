"""
app.schemas.data_source — Pydantic request / response schemas for data ingestion & registry status.

Kept separate from ORM models to maintain a clean boundary between
the API contract and the persistence layer.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Ingestion response sub-models ──────────────────────────────────────────────

class DocumentOut(BaseModel):
    """Single document in the ingestion response."""
    document_id: UUID = Field(..., description="Unique document identifier.")
    file_name: str = Field(..., description="Original uploaded file name.")
    pipeline_status: str = Field(..., description="Document processing status.")
    storage_path: str = Field(
        ..., description="Storage path in object storage."
    )

    model_config = {"from_attributes": True}


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


# ── Registry & Status detailed models ──────────────────────────────────────────

class DocumentDetail(BaseModel):
    """Detailed registry record of a document."""
    document_id: UUID = Field(..., description="Document UUID identifier.")
    file_name: str = Field(..., description="Original uploaded filename.")
    pipeline_status: str = Field(..., description="Current pipeline processing status.")
    storage_path: Optional[str] = Field(None, description="MinIO object storage path.")
    file_size_bytes: Optional[int] = Field(None, description="File size in bytes.")
    content_type: Optional[str] = Field(None, description="MIME content type.")
    language_detected: List[str] = Field(default_factory=list, description="Languages detected during preprocessing.")
    page_count: Optional[int] = Field(None, description="Extracted document page count.")
    error: Optional[str] = Field(None, description="Error detail if status is failed.")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp.")

    model_config = {"from_attributes": True}


class ChunkingSummary(BaseModel):
    """Summary of chunking registry and Qdrant vector store state."""
    job_id: Optional[UUID] = Field(None, description="Chunking job ID (= data_source_id).")
    total_chunks: int = Field(0, description="Total number of chunks generated.")
    chunk_status_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of chunks by lifecycle status (e.g. vector_store_successful, failed).",
    )
    vector_collections: List[str] = Field(
        default_factory=list,
        description="List of Qdrant collection names associated with this connector.",
    )
    embedding_models: List[str] = Field(
        default_factory=list,
        description="List of embedding models used for this connector.",
    )
    embedding_modes: List[str] = Field(
        default_factory=list,
        description="Vector storage modes used (dense, hybrid, sparse).",
    )


class DataSourceDetail(BaseModel):
    """Complete aggregated registry information for a data connector."""
    data_source_id: UUID = Field(..., description="Data source UUID identifier.")
    name: str = Field(..., description="Unique data source name.")
    description: str = Field(..., description="Human-readable description.")
    status: str = Field(..., description="Overall connector status.")
    error: Optional[str] = Field(None, description="Error detail if overall status is failed.")
    config: Dict[str, Any] = Field(default_factory=dict, description="Configuration metadata JSONB.")
    created_at: datetime = Field(..., description="Created timestamp.")
    updated_at: datetime = Field(..., description="Last updated timestamp.")
    document_count: int = Field(..., description="Total number of documents.")
    documents: List[DocumentDetail] = Field(default_factory=list, description="List of documents.")
    chunking_info: Optional[ChunkingSummary] = Field(None, description="Chunking & vector store summary.")

    model_config = {"from_attributes": True}


class DataSourceSummary(BaseModel):
    """Summary item for data connector listing."""
    data_source_id: UUID = Field(..., description="Data source UUID identifier.")
    name: str = Field(..., description="Data source name.")
    description: str = Field(..., description="Description.")
    status: str = Field(..., description="Overall connector status.")
    error: Optional[str] = Field(None, description="Error detail if status is failed.")
    document_count: int = Field(..., description="Number of documents.")
    total_chunks: int = Field(..., description="Total number of chunks.")
    vector_collections: List[str] = Field(default_factory=list, description="Vector collection names.")
    created_at: datetime = Field(..., description="Created timestamp.")
    updated_at: datetime = Field(..., description="Last updated timestamp.")

    model_config = {"from_attributes": True}
