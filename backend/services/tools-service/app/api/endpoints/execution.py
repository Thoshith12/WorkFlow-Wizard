"""
app.api.endpoints.execution — Tool execution endpoint.

POST /api/tools/execute — Execute any tool (system or custom). JWT required.

Returns 503 + Retry-After when the sandbox queue is full (SandboxBusy).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.utils.pool import get_db
from app.api.deps import get_current_user
from app.schemas.execution import ExecuteToolRequest, ExecuteToolResponse
from app.services.execution_engine import (
    ToolExecutionTimeout,
    ToolNotFound,
    ToolOutputTooLarge,
    execution_engine,
)
from app.sandbox.base_executor import SandboxBusy

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/tools/execute",
    response_model=ExecuteToolResponse,
    tags=["Execution"],
    summary="Execute a tool",
)
async def execute_tool(
    body: ExecuteToolRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute any registered tool (system or custom).

    System tools run in-process via ainvoke(). Custom tools run in a
    gVisor sandbox. The response always includes an execution_id for
    audit/debugging and duration_ms for performance monitoring.

    Returns 503 + Retry-After: 5 when the sandbox queue is full.
    """
    executed_by = user.get("sub", "")
    if not executed_by:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim.",
        )

    try:
        result = await execution_engine.execute(
            db,
            tool_name=body.tool_name,
            tool_version=body.tool_version,
            input_data=body.input,
            executed_by=executed_by,
            timeout_seconds=body.timeout_seconds,
        )
        await db.commit()

        return ExecuteToolResponse(**result)

    except ToolNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except SandboxBusy as exc:
        # 503 with Retry-After header — not a silent hang.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
            headers={"Retry-After": "5"},
        )
    except Exception as exc:
        logger.error("Unexpected execution error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution failed: {type(exc).__name__}",
        )
