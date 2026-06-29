"""
app.repositories.data_source — DataSource persistence layer.

All database access for the data_sources table is encapsulated here.
Repositories accept an AsyncSession and return ORM instances —
they never import FastAPI or know about HTTP concerns.
"""
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSource

logger = logging.getLogger(__name__)


async def create_data_source(
    db: AsyncSession,
    *,
    name: str,
    description: str,
    config: Optional[Dict[str, Any]] = None,
) -> DataSource:
    """
    Insert a new DataSource row and flush to obtain the generated UUID.

    Args:
        db:          Active async session (managed by get_db dependency).
        name:        Unique data source name.
        description: Human-readable description.
        config:      Optional JSONB metadata.

    Returns:
        The newly created DataSource ORM instance.
    """
    ds = DataSource(
        name=name,
        description=description,
        config=config or {},
    )
    db.add(ds)
    await db.flush()  # Generate UUID without committing
    await db.refresh(ds)
    logger.info("Created DataSource id=%s name=%r", ds.id, ds.name)
    return ds


async def get_data_source_by_id(
    db: AsyncSession,
    data_source_id: UUID,
) -> Optional[DataSource]:
    """Retrieve a DataSource by primary key, or None if not found."""
    result = await db.execute(
        select(DataSource).where(DataSource.id == data_source_id)
    )
    return result.scalars().first()


async def get_data_source_by_name(
    db: AsyncSession,
    name: str,
) -> Optional[DataSource]:
    """Retrieve a DataSource by unique name, or None if not found."""
    result = await db.execute(
        select(DataSource).where(DataSource.name == name)
    )
    return result.scalars().first()
