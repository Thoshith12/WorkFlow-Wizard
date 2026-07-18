"""
app.services.registry — ToolRegistry singleton.

Provides a unified in-memory index of all tools (system + custom) with
O(1) lookup by (name, version). System tools are loaded from app/tools/
at import time; custom tools are loaded from the database at startup.

Usage:
    from app.services.registry import tool_registry
    tool_def = tool_registry.get("web_search", "1.0.0")
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple, Union

from app.models.custom_tool import CustomTool
from app.models.enums.tools import ToolType
from app.schemas.tool_schema import ToolDefinition, ToolListItem
from app.tools import SYSTEM_TOOLS, SYSTEM_TOOL_NAMES

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Unified registry for system and custom tools.

    System tools are loaded from SYSTEM_TOOLS dict at init time.
    Custom tools are added/removed dynamically as they are created/updated/deleted.

    The registry resolves system tools first — a custom tool can never shadow
    a system tool name (enforced at creation time by the collision check).
    """

    def __init__(self) -> None:
        self._system: Dict[str, ToolDefinition] = dict(SYSTEM_TOOLS)
        self._custom: Dict[str, CustomTool] = {}
        logger.info(
            "ToolRegistry initialized with %d system tools.",
            len(self._system),
        )

    async def load_all(self) -> None:
        """
        Load all active custom tools from the database into the in-memory index.

        Called once at startup by LifespanHandler.
        """
        from shared.database.utils.pool import get_db
        from app.repositories.custom_tool import list_custom_tools

        async for db in get_db():
            tools = await list_custom_tools(db, status="active")
            for tool in tools:
                key = f"{tool.name}@{tool.version}"
                self._custom[key] = tool
            logger.info(
                "Loaded %d custom tools from database.", len(tools)
            )

    # ── Lookups ───────────────────────────────────────────────────────────────

    def get(self, name: str, version: str) -> Optional[Union[ToolDefinition, CustomTool]]:
        """
        Retrieve a tool by (name, version).

        System tools take precedence. Returns None if not found.
        """
        key = f"{name}@{version}"
        # System first
        if key in self._system:
            return self._system[key]
        # Then custom
        return self._custom.get(key)

    def get_tool_type(self, name: str, version: str) -> Optional[ToolType]:
        """Determine the tool type for a (name, version) pair."""
        key = f"{name}@{version}"
        if key in self._system:
            return ToolType.SYSTEM
        if key in self._custom:
            return ToolType.CUSTOM
        return None

    def list_all(self, tool_type: Optional[str] = None) -> List[ToolListItem]:
        """
        Return a list of all registered tools (system + custom) as ToolListItems.

        Optionally filtered by tool_type ("system" or "custom").
        """
        items: List[ToolListItem] = []

        if tool_type is None or tool_type == "system":
            for defn in self._system.values():
                items.append(ToolListItem(
                    name=defn.name,
                    version=defn.version,
                    display_name=defn.display_name,
                    description=defn.description,
                    tool_type=ToolType.SYSTEM,
                    capabilities=defn.capabilities,
                    tags=[],
                    status="active",
                ))

        if tool_type is None or tool_type == "custom":
            for ct in self._custom.values():
                items.append(ToolListItem(
                    name=ct.name,
                    version=ct.version,
                    display_name=ct.display_name,
                    description=ct.description,
                    tool_type=ToolType.CUSTOM,
                    capabilities=ct.capabilities or [],
                    tags=ct.tags or [],
                    status=ct.status,
                ))

        return items

    # ── Collision check ───────────────────────────────────────────────────────

    def would_shadow_system_tool(self, name: str) -> bool:
        """
        Check if a custom tool name would shadow a system tool.

        This is called at creation time. Custom tools can never shadow
        system tool names — returns True if the name collides.
        """
        return name in SYSTEM_TOOL_NAMES

    # ── Dynamic registration ──────────────────────────────────────────────────

    def register_custom(self, tool: CustomTool) -> None:
        """Add or update a custom tool in the in-memory index."""
        key = f"{tool.name}@{tool.version}"
        self._custom[key] = tool
        logger.info("Registered custom tool: %s", key)

    def unregister_custom(self, name: str, version: str) -> None:
        """Remove a custom tool from the in-memory index."""
        key = f"{name}@{version}"
        self._custom.pop(key, None)
        logger.info("Unregistered custom tool: %s", key)


# Module-level singleton
tool_registry = ToolRegistry()
