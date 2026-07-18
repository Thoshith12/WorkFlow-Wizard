"""
app.api.endpoints.custom_tools — Custom tool CRUD endpoints.

POST   /api/tools/custom                  — Create a new custom tool.
GET    /api/tools/custom/{name}/{version}  — Get full custom tool detail.
PATCH  /api/tools/custom/{name}/{version}  — Update (owner only).
DELETE /api/tools/custom/{name}/{version}  — Delete (owner only).

All endpoints require JWT authentication. PATCH and DELETE are
owner-gated: only the user who created the tool (owner_id == token sub)
can modify or delete it.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.utils.pool import get_db
from app.api.deps import get_current_user
from app.repositories import custom_tool as repo
from app.schemas.custom_tool import CustomToolCreate, CustomToolDetail, CustomToolUpdate
from app.services.custom_tool_manager import custom_tool_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/tools/custom",
    response_model=CustomToolDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["Custom Tools"],
    summary="Create custom tool",
)
async def create_custom_tool(
    body: CustomToolCreate,
    user: Dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomToolDetail:
    """
    Register a new custom tool.

    The (name, version) pair must be unique and must not shadow any
    system tool name. The authenticated user becomes the tool owner.
    """
    owner_id = user.get("sub", "")
    if not owner_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim.",
        )

    try:
        tool = await custom_tool_manager.create(
            db,
            owner_id=owner_id,
            data=body.model_dump(),
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    return _to_detail(tool)


@router.get(
    "/tools/custom/{name}/{version}",
    response_model=CustomToolDetail,
    tags=["Custom Tools"],
    summary="Get custom tool detail",
)
async def get_custom_tool_detail(
    name: str,
    version: str,
    _user: Dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomToolDetail:
    """
    Full custom tool definition — code, imports, requirements, config KEYS.

    Config VALUES are redacted. This response doubles as a reference
    payload for the PATCH endpoint.
    """
    tool = await repo.get_custom_tool(db, name, version)
    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Custom tool '{name}@{version}' not found.",
        )
    return _to_detail(tool)


@router.patch(
    "/tools/custom/{name}/{version}",
    response_model=CustomToolDetail,
    tags=["Custom Tools"],
    summary="Update custom tool (owner only)",
)
async def update_custom_tool(
    name: str,
    version: str,
    body: CustomToolUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomToolDetail:
    """
    Update a custom tool. Owner-gated — only the creator can modify.

    name and version are immutable. If requirements, imports, or config
    change, the sandbox container is invalidated and will be re-booted
    with the new dependencies on next execution.
    """
    owner_id = user.get("sub", "")
    tool = await repo.get_custom_tool(db, name, version)
    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Custom tool '{name}@{version}' not found.",
        )

    try:
        updated = await custom_tool_manager.update(
            db,
            tool=tool,
            owner_id=owner_id,
            update_data=body.model_dump(exclude_unset=True),
        )
        await db.commit()
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return _to_detail(updated)


@router.delete(
    "/tools/custom/{name}/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Custom Tools"],
    summary="Delete custom tool (owner only)",
)
async def delete_custom_tool(
    name: str,
    version: str,
    user: Dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a custom tool. Owner-gated — only the creator can delete.

    Removes the tool from the database, the in-memory registry, and
    invalidates any running sandbox container.
    """
    owner_id = user.get("sub", "")
    tool = await repo.get_custom_tool(db, name, version)
    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Custom tool '{name}@{version}' not found.",
        )

    try:
        await custom_tool_manager.delete(
            db,
            tool=tool,
            owner_id=owner_id,
        )
        await db.commit()
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )


# ── Helper ────────────────────────────────────────────────────────────────────


def _to_detail(tool) -> CustomToolDetail:
    """Convert a CustomTool ORM instance to a CustomToolDetail response."""
    return CustomToolDetail(
        id=str(tool.id),
        name=tool.name,
        version=tool.version,
        display_name=tool.display_name,
        description=tool.description,
        owner_id=tool.owner_id,
        preprocessing_code=tool.preprocessing_code,
        processing_code=tool.processing_code,
        postprocessing_code=tool.postprocessing_code,
        input_schema=tool.input_schema or {},
        output_schema=tool.output_schema,
        usage_examples=tool.usage_examples or [],
        imports=tool.imports or [],
        requirements=tool.requirements or [],
        config_keys=list((tool.config or {}).keys()),  # values redacted
        tags=tool.tags or [],
        capabilities=tool.capabilities or [],
        status=tool.status,
        created_at=tool.created_at.isoformat(),
        updated_at=tool.updated_at.isoformat(),
    )
