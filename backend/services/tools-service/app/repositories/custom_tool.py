"""
app.repositories.custom_tool — CustomTool persistence layer.

All database access for the custom_tool_registry table is encapsulated here.
Follows the same pattern as rag-service repositories.
"""
import hashlib
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_tool import CustomTool

logger = logging.getLogger(__name__)


async def create_custom_tool(
    db: AsyncSession,
    *,
    name: str,
    version: str,
    display_name: str,
    description: str,
    owner_id: str,
    processing_code: str,
    preprocessing_code: Optional[str] = None,
    postprocessing_code: Optional[str] = None,
    input_schema: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Dict[str, Any]] = None,
    usage_examples: Optional[List[Dict[str, Any]]] = None,
    imports: Optional[List[str]] = None,
    requirements: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
    capabilities: Optional[List[str]] = None,
) -> CustomTool:
    """
    Insert a new CustomTool row and flush to obtain the generated UUID.

    Computes venv_hash from sorted requirements for disk-cache keying.
    """
    # Compute venv hash from requirements
    reqs = sorted(requirements or [])
    venv_hash = hashlib.sha256("|".join(reqs).encode()).hexdigest() if reqs else None

    tool = CustomTool(
        name=name,
        version=version,
        display_name=display_name,
        description=description,
        owner_id=owner_id,
        processing_code=processing_code,
        preprocessing_code=preprocessing_code,
        postprocessing_code=postprocessing_code,
        input_schema=input_schema or {},
        output_schema=output_schema,
        usage_examples=usage_examples or [],
        imports=imports or [],
        requirements=requirements or [],
        venv_hash=venv_hash,
        config=config or {},
        tags=tags or [],
        capabilities=capabilities or [],
    )
    db.add(tool)
    await db.flush()
    await db.refresh(tool)
    logger.info("Created CustomTool id=%s name=%r version=%r", tool.id, tool.name, tool.version)
    return tool


async def get_custom_tool(
    db: AsyncSession,
    name: str,
    version: str,
) -> Optional[CustomTool]:
    """Retrieve a custom tool by (name, version)."""
    result = await db.execute(
        select(CustomTool).where(
            and_(CustomTool.name == name, CustomTool.version == version)
        )
    )
    return result.scalar_one_or_none()


async def get_custom_tool_by_id(
    db: AsyncSession,
    tool_id: UUID,
) -> Optional[CustomTool]:
    """Retrieve a custom tool by primary key."""
    result = await db.execute(
        select(CustomTool).where(CustomTool.id == tool_id)
    )
    return result.scalar_one_or_none()


async def list_custom_tools(
    db: AsyncSession,
    *,
    status: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> List[CustomTool]:
    """List all custom tools, optionally filtered by status and/or owner."""
    stmt = select(CustomTool).order_by(CustomTool.created_at.desc())
    if status:
        stmt = stmt.where(CustomTool.status == status)
    if owner_id:
        stmt = stmt.where(CustomTool.owner_id == owner_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_custom_tool(
    db: AsyncSession,
    tool: CustomTool,
    update_data: Dict[str, Any],
) -> CustomTool:
    """
    Patch a CustomTool with the given update fields.

    Recomputes venv_hash if requirements changed.
    """
    for key, value in update_data.items():
        if value is not None:
            setattr(tool, key, value)

    # Recompute venv_hash if requirements changed
    if "requirements" in update_data and update_data["requirements"] is not None:
        reqs = sorted(update_data["requirements"])
        tool.venv_hash = hashlib.sha256("|".join(reqs).encode()).hexdigest() if reqs else None

    await db.flush()
    await db.refresh(tool)
    logger.info("Updated CustomTool id=%s name=%r", tool.id, tool.name)
    return tool


async def delete_custom_tool(
    db: AsyncSession,
    tool: CustomTool,
) -> None:
    """Delete a custom tool record."""
    logger.info("Deleting CustomTool id=%s name=%r", tool.id, tool.name)
    await db.delete(tool)
    await db.flush()
