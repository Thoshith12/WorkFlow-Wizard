"""
app.models.execution_log — ExecutionLog ORM model.

Records every tool execution attempt — both system and custom.
Used for audit, debugging, and monitoring. Execution logs must NEVER
capture config.json contents (secrets leak risk).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from shared.database.utils.pool import Base


class ExecutionLog(Base):
    __tablename__ = "execution_log"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tool_name = Column(String(255), nullable=False, index=True)
    tool_version = Column(String(50), nullable=False)
    tool_type = Column(String(50), nullable=False)       # system / custom
    executed_by = Column(String(255), nullable=False, index=True)  # Keycloak sub
    input_payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    output_payload = Column(JSONB, nullable=True)
    status = Column(String(50), nullable=False, index=True)  # success / error / timeout
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Float, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<ExecutionLog tool={self.tool_name!r}@{self.tool_version} "
            f"status={self.status!r} by={self.executed_by!r}>"
        )
