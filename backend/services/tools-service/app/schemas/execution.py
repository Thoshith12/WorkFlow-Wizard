"""
app.schemas.execution — Pydantic schemas for tool execution requests/responses.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ExecuteToolRequest(BaseModel):
    """Request body for POST /api/tools/execute."""

    tool_name: str = Field(..., min_length=1, max_length=255)
    tool_version: str = Field(..., min_length=1, max_length=50)
    input: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=300)


class ExecuteToolResponse(BaseModel):
    """Response body for POST /api/tools/execute."""

    execution_id: str
    tool_name: str
    tool_version: str
    tool_type: str  # system / custom
    status: str     # success / error / timeout
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: Optional[float] = None
