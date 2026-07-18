"""
app.repositories.execution_log — ExecutionLog persistence layer.

All database access for the execution_log table is encapsulated here.
Execution logs must NEVER capture config.json contents (secrets leak risk).
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution_log import ExecutionLog

logger = logging.getLogger(__name__)


async def create_execution_log(
    db: AsyncSession,
    *,
    tool_name: str,
    tool_version: str,
    tool_type: str,
    executed_by: str,
    input_payload: Dict[str, Any],
    output_payload: Optional[Dict[str, Any]] = None,
    status: str,
    error_message: Optional[str] = None,
    duration_ms: Optional[float] = None,
) -> ExecutionLog:
    """
    Insert a new ExecutionLog row.

    IMPORTANT: error_message is truncated to 500 chars to prevent
    config/secret values from leaking via stack traces.
    """
    log = ExecutionLog(
        tool_name=tool_name,
        tool_version=tool_version,
        tool_type=tool_type,
        executed_by=executed_by,
        input_payload=input_payload,
        output_payload=output_payload,
        status=status,
        error_message=error_message[:500] if error_message else None,
        duration_ms=duration_ms,
    )
    db.add(log)
    await db.flush()
    await db.refresh(log)
    return log


async def get_execution_log(
    db: AsyncSession,
    execution_id: UUID,
) -> Optional[ExecutionLog]:
    """Retrieve a single execution log by ID."""
    result = await db.execute(
        select(ExecutionLog).where(ExecutionLog.id == execution_id)
    )
    return result.scalar_one_or_none()


async def list_execution_logs(
    db: AsyncSession,
    *,
    tool_name: Optional[str] = None,
    executed_by: Optional[str] = None,
    limit: int = 50,
) -> List[ExecutionLog]:
    """List execution logs, optionally filtered by tool name or user."""
    stmt = select(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(limit)
    if tool_name:
        stmt = stmt.where(ExecutionLog.tool_name == tool_name)
    if executed_by:
        stmt = stmt.where(ExecutionLog.executed_by == executed_by)
    result = await db.execute(stmt)
    return list(result.scalars().all())
