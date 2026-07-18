"""
app.models.chunk — Chunk ORM model.

Represents a single text chunk produced by the chunking pipeline from a
preprocessed document page. Each chunk is tracked from creation through
embedding to vector store insertion via the `status` column.

Lifecycle statuses (see ChunkStatus enum):
    initiated → chunking → embedding → embeddings_generated
                                     → vector_store_successful
                                     → failed  (at any stage)

The `config` JSONB column stores the full chunking configuration snapshot
that was active when this chunk was created (strategy, sizes, model list,
embedding mode, etc.), enabling full reproducibility and audit.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from shared.database.utils.pool import Base


class Chunk(Base):
    __tablename__ = "chunk_registry"

    # ── Primary key ───────────────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # ── Job / parent references ───────────────────────────────────────────────
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_source_registry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The chunking job identifier — equals data_source_id for the initiating request.",
    )
    data_source_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_source_registry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_registry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Chunk content ─────────────────────────────────────────────────────────
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Globally sequential 0-based index across all docs in this job.",
    )
    chunk_language = Column(
        String(10),
        nullable=True,
        comment="ISO 639-1 two-letter code detected for this chunk's source page.",
    )
    page_number = Column(
        Integer,
        nullable=True,
        comment="Source document page number from which this chunk was derived.",
    )

    # ── Chunking configuration snapshot ──────────────────────────────────────
    config = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Full chunking + embedding config active when this chunk was created.",
    )

    # ── Embedding & vector store info ─────────────────────────────────────────
    embedding_model = Column(
        String(255),
        nullable=True,
        comment="HuggingFace model repo name used to embed this chunk.",
    )
    vector_collection = Column(
        String(255),
        nullable=True,
        comment="Qdrant collection name: {data_source_id}_{model_short_name}_{dims}.",
    )

    # ── Lifecycle tracking ────────────────────────────────────────────────────
    status = Column(
        String(50),
        nullable=False,
        default="initiated",
        server_default=text("'initiated'"),
        index=True,
        comment="ChunkStatus enum value.",
    )
    error = Column(
        Text,
        nullable=True,
        comment="Human-readable error detail when status=failed.",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<Chunk id={self.id} index={self.chunk_index} "
            f"lang={self.chunk_language!r} status={self.status!r}>"
        )
