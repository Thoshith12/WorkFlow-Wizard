"""
app.models.custom_tool — CustomTool ORM model.

Represents a user-submitted custom tool registration. Each custom tool:
- Is uniquely identified by (name, version) — both immutable after creation.
- Stores processing code, imports, pip requirements, and config.
- Is owned by the JWT-authenticated user who created it.
- Config values are encrypted at rest (AES-256-GCM, mandatory).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from shared.database.utils.pool import Base


class CustomTool(Base):
    __tablename__ = "custom_tool_registry"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_custom_tool_name_version"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name = Column(String(255), nullable=False, index=True)
    version = Column(String(50), nullable=False)  # e.g. "1.0.0" — immutable
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    owner_id = Column(String(255), nullable=False, index=True)  # Keycloak sub — immutable

    # Code fields (validated against blocked imports + substring scan at registration)
    preprocessing_code = Column(Text, nullable=True)
    processing_code = Column(Text, nullable=False)  # must define async def process(input_data)
    postprocessing_code = Column(Text, nullable=True)

    # I/O contract
    input_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    output_schema = Column(JSONB, nullable=True)
    usage_examples = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    # Dependencies — all accepted at creation and patchable at update
    imports = Column(ARRAY(String), nullable=False, server_default=text("ARRAY[]::varchar[]"))
    requirements = Column(ARRAY(String), nullable=False, server_default=text("ARRAY[]::varchar[]"))
    venv_hash = Column(String(64), nullable=True)  # sha256(sorted(requirements))

    # Tool-scoped config — stored encrypted in DB (mandatory, AES-256-GCM).
    # Written to /run/sandbox/config.json on container boot by the trusted runner.
    # Keys are strings; values are any JSON-serialisable type.
    # NEVER exposed as process env vars. Isolated per tool.
    config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    # Metadata
    tags = Column(ARRAY(String), nullable=False, server_default=text("ARRAY[]::varchar[]"))
    capabilities = Column(ARRAY(String), nullable=False, server_default=text("ARRAY[]::varchar[]"))
    status = Column(
        String(50),
        nullable=False,
        default="active",
        server_default=text("'active'"),
        index=True,
    )

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
        return f"<CustomTool name={self.name!r} version={self.version!r} owner={self.owner_id!r}>"
