"""
app.models.document — Document ORM model.

Represents a single uploaded file within a DataSource. Tracks the file's
lifecycle from upload through processing stages.

The `config` JSONB blob stores per-document metadata that varies by file
type and pipeline stage (storage path, MIME type, byte size, etc.).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from shared.database.utils.pool import Base


class Document(Base):
    __tablename__ = "document_registry"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    data_source_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_source_registry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_name = Column(String(512), nullable=False)
    
    # ── Pipeline tracking (migration 004 refactored) ──────────────────────────
    pipeline_status = Column(
        String(50), 
        nullable=False, 
        default="pending",
        server_default=text("'pending'"),
        index=True
    )
    language_detected = Column(
        JSONB,
        nullable=True,
        server_default=text("'[]'::jsonb"),
    )
    errors = Column(
        JSONB,
        nullable=True,
        server_default=text("'{}'::jsonb"),
    )

    config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

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

    # Relationship back to parent DataSource
    data_source = relationship("DataSource", back_populates="documents")

    def __repr__(self) -> str:
        return (
            f"<Document id={self.id} file={self.file_name!r} "
            f"pipeline_status={self.pipeline_status!r}>"
        )


