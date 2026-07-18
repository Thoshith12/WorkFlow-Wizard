"""
app.services.custom_tool_manager — Custom tool lifecycle management.

Handles the business logic layer for custom tool CRUD — sits between
the API endpoints and the repository/registry. Responsible for:
  - System tool name collision checks
  - Ownership validation
  - venv hash computation and sandbox container invalidation
  - Registry synchronization
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_tool import CustomTool
from app.repositories import custom_tool as repo
from app.services.registry import tool_registry

logger = logging.getLogger(__name__)


class CustomToolManager:
    """Business logic for custom tool CRUD operations."""

    async def create(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        data: Dict[str, Any],
    ) -> CustomTool:
        """
        Create a new custom tool.

        Validates:
          - Name does not shadow a system tool.
          - (name, version) is unique in the database.

        On success, registers the tool in the in-memory registry.
        """
        name = data["name"]
        version = data["version"]

        # Collision check against system tools
        if tool_registry.would_shadow_system_tool(name):
            raise ValueError(
                f"Tool name '{name}' conflicts with a system tool. "
                "Custom tools cannot shadow system tool names."
            )

        # Check uniqueness (DB unique constraint is the final guard,
        # but we give a better error message here).
        existing = await repo.get_custom_tool(db, name, version)
        if existing:
            raise ValueError(
                f"Custom tool '{name}@{version}' already exists. "
                "Use a different version number to create a new variant."
            )

        tool = await repo.create_custom_tool(
            db,
            name=name,
            version=version,
            display_name=data["display_name"],
            description=data["description"],
            owner_id=owner_id,
            processing_code=data["processing_code"],
            preprocessing_code=data.get("preprocessing_code"),
            postprocessing_code=data.get("postprocessing_code"),
            input_schema=data.get("input_schema"),
            output_schema=data.get("output_schema"),
            usage_examples=data.get("usage_examples"),
            imports=data.get("imports"),
            requirements=data.get("requirements"),
            config=data.get("config"),
            tags=data.get("tags"),
            capabilities=data.get("capabilities"),
        )

        # Register in in-memory index
        tool_registry.register_custom(tool)
        logger.info("Created custom tool: %s@%s by %s", name, version, owner_id)
        return tool

    async def update(
        self,
        db: AsyncSession,
        *,
        tool: CustomTool,
        owner_id: str,
        update_data: Dict[str, Any],
    ) -> CustomTool:
        """
        Update an existing custom tool.

        Validates:
          - Caller is the owner.
          - name and version are not being changed.

        If requirements, imports, or config change, the existing gVisor
        container for this tool must be invalidated (restarted with new
        venv/config on next execution).
        """
        if tool.owner_id != owner_id:
            raise PermissionError("Only the tool owner can update this tool.")

        # name and version are immutable
        if "name" in update_data or "version" in update_data:
            raise ValueError("name and version are immutable after creation.")

        # Detect if sandbox-invalidating fields changed
        sandbox_changed = any(
            key in update_data and update_data[key] is not None
            for key in ("requirements", "imports", "config")
        )

        updated = await repo.update_custom_tool(db, tool, update_data)

        # Re-register in index
        tool_registry.register_custom(updated)

        if sandbox_changed:
            # Invalidate the existing gVisor container for this tool.
            # On next execution, a new container will be booted with the
            # updated venv and config.
            try:
                from app.sandbox.pool import sandbox_pool
                await sandbox_pool.invalidate(tool.name, tool.version)
                logger.info(
                    "Sandbox invalidated for %s@%s (requirements/imports/config changed).",
                    tool.name, tool.version,
                )
            except Exception as exc:
                logger.warning("Failed to invalidate sandbox for %s@%s: %s", tool.name, tool.version, exc)

        return updated

    async def delete(
        self,
        db: AsyncSession,
        *,
        tool: CustomTool,
        owner_id: str,
    ) -> None:
        """
        Delete a custom tool.

        Validates caller is the owner. Removes from database, registry,
        and invalidates any running sandbox container.
        """
        if tool.owner_id != owner_id:
            raise PermissionError("Only the tool owner can delete this tool.")

        name, version = tool.name, tool.version

        await repo.delete_custom_tool(db, tool)
        tool_registry.unregister_custom(name, version)

        # Invalidate sandbox container
        try:
            from app.sandbox.pool import sandbox_pool
            await sandbox_pool.invalidate(name, version)
        except Exception as exc:
            logger.warning("Failed to invalidate sandbox for %s@%s: %s", name, version, exc)

        logger.info("Deleted custom tool: %s@%s by %s", name, version, owner_id)


# Module-level singleton
custom_tool_manager = CustomToolManager()
