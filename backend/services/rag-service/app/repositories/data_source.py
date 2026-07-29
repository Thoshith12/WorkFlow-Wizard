"""
app.repositories.data_source — DataSource persistence layer.

All database access for the data_sources table is encapsulated here.
Repositories accept an AsyncSession and return ORM instances —
they never import FastAPI or know about HTTP concerns.
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSource
from app.models.document import Document
from app.models.chunk import Chunk

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


async def get_all_data_sources(
    db: AsyncSession,
) -> List[DataSource]:
    """Retrieve all data sources ordered by creation date (newest first)."""
    result = await db.execute(
        select(DataSource).order_by(DataSource.created_at.desc())
    )
    return list(result.scalars().all())


async def get_chunk_summary_for_data_source(
    db: AsyncSession,
    data_source_id: UUID,
) -> Dict[str, Any]:
    """
    Query chunk_registry to construct a summary of chunking & vector store status.
    """
    chunks_result = await db.execute(
        select(Chunk).where(Chunk.data_source_id == data_source_id)
    )
    chunks: List[Chunk] = list(chunks_result.scalars().all())

    status_counts: Dict[str, int] = {}
    collections_set = set()
    models_set = set()
    modes_set = set()
    job_id = None

    for c in chunks:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1
        if c.vector_collection:
            collections_set.add(c.vector_collection)
        if c.embedding_model:
            models_set.add(c.embedding_model)
        if c.config and isinstance(c.config, dict):
            if "embedding_mode" in c.config:
                modes_set.add(c.config["embedding_mode"])
            if "embedding_models" in c.config:
                for m in c.config["embedding_models"]:
                    models_set.add(m)
        if c.job_id:
            job_id = c.job_id

    return {
        "job_id": job_id or data_source_id,
        "total_chunks": len(chunks),
        "chunk_status_counts": status_counts,
        "vector_collections": list(collections_set),
        "embedding_models": list(models_set),
        "embedding_modes": list(modes_set),
    }
