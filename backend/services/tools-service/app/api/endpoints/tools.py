"""
app.api.endpoints.tools — Universal tool listing and schema discovery.

GET /api/tools             — List all tools (system + custom), with optional
                             ?tool_type=system|custom filter. JWT required.
GET /api/tools/{name}/{version}/schema — Full schema for any tool. JWT required.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.models.custom_tool import CustomTool
from app.models.enums.tools import ToolType
from app.schemas.tool_schema import ToolDefinition, ToolListItem, ToolSchemaResponse
from app.services.registry import tool_registry

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/tools",
    response_model=List[ToolListItem],
    tags=["Tools"],
    summary="List all tools",
)
async def list_tools(
    tool_type: Optional[str] = Query(
        None,
        description="Filter by tool type: 'system' or 'custom'. Omit for all.",
        regex="^(system|custom)$",
    ),
    _user: Dict[str, Any] = Depends(get_current_user),
) -> List[ToolListItem]:
    """
    Universal tool listing.

    Returns all registered tools (system + custom) with the `tool_type`
    discriminator so the UI knows how to render each one. Optionally
    filtered by tool_type.
    """
    return tool_registry.list_all(tool_type=tool_type)


@router.get(
    "/tools/{name}/{version}/schema",
    response_model=ToolSchemaResponse,
    tags=["Tools"],
    summary="Get tool schema",
)
async def get_tool_schema(
    name: str,
    version: str,
    _user: Dict[str, Any] = Depends(get_current_user),
) -> ToolSchemaResponse:
    """
    Full schema discovery for a tool.

    Returns everything an LLM or UI needs to understand how to call
    the tool, what inputs it expects, and what outputs it produces.
    Works for both system and custom tools.
    """
    tool = tool_registry.get(name, version)
    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{name}@{version}' not found.",
        )

    tool_type = tool_registry.get_tool_type(name, version)

    if isinstance(tool, ToolDefinition):
        return ToolSchemaResponse(
            name=tool.name,
            version=tool.version,
            display_name=tool.display_name,
            description=tool.description,
            tool_type=tool_type or ToolType.SYSTEM,
            capabilities=tool.capabilities,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            usage_examples=tool.usage_examples,
        )
    elif isinstance(tool, CustomTool):
        return ToolSchemaResponse(
            name=tool.name,
            version=tool.version,
            display_name=tool.display_name,
            description=tool.description,
            tool_type=ToolType.CUSTOM,
            capabilities=tool.capabilities or [],
            input_schema=tool.input_schema or {},
            output_schema=tool.output_schema,
            usage_examples=tool.usage_examples or [],
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unknown tool type in registry.",
        )
