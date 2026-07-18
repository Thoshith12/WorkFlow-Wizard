"""
app.schemas.tool_schema — Shared schema types for both system and custom tools.

ToolDefinition:    Internal dataclass used by system tools to register themselves.
ToolSchemaResponse: API response for GET /api/tools/{name}/{version}/schema.
ToolListItem:       API response item for GET /api/tools listing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.models.enums.tools import ToolType


@dataclass
class ToolDefinition:
    """
    Internal registration record for a system tool.

    Each system tool file in app/tools/ exports one of these.
    The `langchain_tool` field holds the instantiated LangChain BaseTool
    for in-process invocation via ainvoke().
    """

    name: str
    version: str
    display_name: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Optional[Dict[str, Any]] = None
    usage_examples: List[Dict[str, Any]] = field(default_factory=list)
    langchain_tool: Any = None  # LangChain BaseTool instance
    max_output_bytes: int = 1_048_576  # 1 MB default
    timeout_seconds: int = 30


# ── API Response Schemas ──────────────────────────────────────────────────────


class ToolListItem(BaseModel):
    """Single item in the universal tool listing (GET /api/tools)."""

    name: str
    version: str
    display_name: str
    description: str
    tool_type: ToolType
    capabilities: List[str] = []
    tags: List[str] = []
    status: str = "active"

    model_config = {"from_attributes": True}


class ToolSchemaResponse(BaseModel):
    """
    Full schema discovery response for a tool (GET /api/tools/{name}/{version}/schema).

    Contains everything an LLM or UI needs to understand how to call the tool,
    what inputs it expects, and what outputs it produces.
    """

    name: str
    version: str
    display_name: str
    description: str
    tool_type: ToolType
    capabilities: List[str] = []
    input_schema: Dict[str, Any] = {}
    output_schema: Optional[Dict[str, Any]] = None
    usage_examples: List[Dict[str, Any]] = []

    model_config = {"from_attributes": True}
