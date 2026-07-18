"""
app.schemas.chunking — Pydantic schemas for the chunking & embedding pipeline.

Request / Response contract for:
    POST /api/data-sources/{data_source_id}/chunk

Design:
  - Each chunking strategy has its own typed config sub-model so callers
    only need to supply the fields relevant to their chosen strategy.
    Unused strategy configs are ignored by the pipeline.
  - embedding_models is an ordered list; the first model that supports a
    chunk's detected language is used. Later models act as fallbacks.
"""
from typing import List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums.chunking import ChunkingStrategy, EmbeddingMode


# ── Per-strategy chunking configuration sub-models ────────────────────────────

class FixedChunkConfig(BaseModel):
    """Configuration for fixed-size character chunking."""
    chunk_size: int = Field(
        512,
        ge=50,
        le=8192,
        description="Number of characters per chunk.",
    )
    chunk_overlap: int = Field(
        50,
        ge=0,
        le=512,
        description="Number of overlapping characters between consecutive chunks.",
    )


class RecursiveChunkConfig(BaseModel):
    """Configuration for recursive character text splitting."""
    chunk_size: int = Field(
        512,
        ge=50,
        le=8192,
        description="Target chunk size in characters.",
    )
    chunk_overlap: int = Field(
        50,
        ge=0,
        le=512,
        description="Overlap in characters between consecutive chunks.",
    )
    separators: List[str] = Field(
        default=["\n\n", "\n", ".", " ", ""],
        description=(
            "Ordered list of separators to try when splitting. "
            "The splitter tries each in turn before doing a hard cut."
        ),
    )


class SemanticChunkConfig(BaseModel):
    """Configuration for embedding-based semantic chunking."""
    breakpoint_threshold: float = Field(
        0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Cosine distance threshold above which a sentence boundary "
            "is treated as a semantic breakpoint. Lower = more splits."
        ),
    )
    min_chunk_size: int = Field(
        100,
        ge=10,
        description="Minimum number of characters a semantic chunk must contain.",
    )


class ParentChildChunkConfig(BaseModel):
    """Configuration for two-pass parent-child chunking."""
    parent_chunk_size: int = Field(
        2048,
        ge=256,
        le=32768,
        description="Character size of the coarse parent chunks.",
    )
    child_chunk_size: int = Field(
        512,
        ge=50,
        le=4096,
        description="Character size of the fine child chunks derived from parents.",
    )
    overlap: int = Field(
        50,
        ge=0,
        le=512,
        description="Overlap in characters between consecutive child chunks.",
    )


class AgenticChunkConfig(BaseModel):
    """Configuration for LLM-driven agentic chunking (Claude Haiku 4.5)."""
    system_prompt: str = Field(
        (
            "You are an expert technical editor specialising in information retrieval. "
            "Your task is to split the provided text into self-contained, semantically "
            "coherent chunks suitable for a RAG (Retrieval-Augmented Generation) system. "
            "Each chunk must:\n"
            "  1. Be independently understandable without surrounding context.\n"
            "  2. Cover a single topic or idea.\n"
            "  3. Respect natural sentence and paragraph boundaries where possible.\n"
            "Return ONLY a JSON array of strings, where each string is one chunk. "
            "Do not include any explanation, preamble, or markdown fencing."
        ),
        description="System prompt passed to Claude Haiku 4.5 for boundary decisions.",
    )
    max_chunk_size: int = Field(
        800,
        ge=100,
        le=8192,
        description="Maximum number of characters the LLM should target per chunk.",
    )
    min_chunk_size: int = Field(
        100,
        ge=10,
        description="Minimum number of characters per LLM-decided chunk.",
    )


# ── Main request schema ───────────────────────────────────────────────────────

class ChunkingRequest(BaseModel):
    """
    Request body for POST /api/data-sources/{data_source_id}/chunk.

    Initiates the chunking + embedding pipeline for a data connector whose
    documents must all have pipeline_status = "preprocessing completed".
    """

    chunking_strategy: ChunkingStrategy = Field(
        ...,
        description="Text chunking strategy to apply.",
        examples=["recursive"],
    )
    embedding_mode: EmbeddingMode = Field(
        ...,
        description=(
            "Vector storage mode: dense, hybrid (dense + BM25 sparse), "
            "or sparse (BM25 only)."
        ),
        examples=["dense"],
    )
    embedding_models: List[str] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered list of HuggingFace model names to use for embedding. "
            "The first model that supports a chunk's detected language is used; "
            "subsequent entries act as fallbacks. "
            "A chunk is marked FAILED if no model in the list supports its language."
        ),
        examples=[["sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "microsoft/harrier-oss-v1-0.6b"]],
    )

    # Per-strategy configuration blocks (only the active strategy's config is used)
    fixed_config: FixedChunkConfig = Field(
        default_factory=FixedChunkConfig,
        description="Configuration for the 'fixed' chunking strategy.",
    )
    recursive_config: RecursiveChunkConfig = Field(
        default_factory=RecursiveChunkConfig,
        description="Configuration for the 'recursive' chunking strategy.",
    )
    semantic_config: SemanticChunkConfig = Field(
        default_factory=SemanticChunkConfig,
        description="Configuration for the 'semantic' chunking strategy.",
    )
    parent_child_config: ParentChildChunkConfig = Field(
        default_factory=ParentChildChunkConfig,
        description="Configuration for the 'parent_child' chunking strategy.",
    )
    agentic_config: AgenticChunkConfig = Field(
        default_factory=AgenticChunkConfig,
        description="Configuration for the 'agentic' chunking strategy (Claude Haiku 4.5).",
    )

    # Celery batching controls
    chunks_per_batch: int = Field(
        50,
        ge=1,
        le=500,
        description="Number of chunks per Celery embedding batch task.",
    )
    pages_per_batch: int = Field(
        10,
        ge=1,
        le=100,
        description="Number of document pages per Celery chunking batch task.",
    )

    @field_validator("embedding_models")
    @classmethod
    def embedding_models_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("At least one embedding model must be specified.")
        return v


# ── Response schema ───────────────────────────────────────────────────────────

class ChunkingResponse(BaseModel):
    """Response returned immediately after the chunking job is initiated."""
    data_source_id: UUID = Field(..., description="Data source identifier.")
    job_id: UUID = Field(..., description="Chunking job identifier (= data_source_id).")
    status: str = Field(..., description="Job status — always 'initiated' on success.")
    chunking_strategy: str = Field(..., description="Chunking strategy that will be applied.")
    embedding_mode: str = Field(..., description="Qdrant vector storage mode.")
    embedding_models: List[str] = Field(..., description="Ordered fallback model list.")
    vector_collection: str = Field(
        ...,
        description=(
            "Qdrant collection name that will be created/used: "
            "{data_source_id}_{primary_model_short_name}_{dims}."
        ),
    )
    message: str = Field(..., description="Human-readable status message.")

    model_config = {"from_attributes": True}
