"""
app.models.data_source — DataSource ORM model.

Represents a logical collection of uploaded documents (e.g. a project,
a knowledge base, or a batch upload). Each DataSource owns zero-to-many
Document records.

The `config` JSONB column is intentionally schema-free to accommodate
evolving metadata requirements without schema migrations.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from shared.database.utils.pool import Base


class DataSource(Base):
    __tablename__ = "data_source_registry"


    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False, default="")
    config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(
        String(50),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        index=True,
    )
    error = Column(Text, nullable=True)

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

    # Relationship — eagerly available when needed
    documents = relationship(
        "Document",
        back_populates="data_source",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<DataSource id={self.id} name={self.name!r}>"
