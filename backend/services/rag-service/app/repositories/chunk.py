"""
app.repositories.chunk — Chunk persistence layer.

All database access for chunk_registry is encapsulated here.
Repositories accept an AsyncSession and return ORM instances —
they never import FastAPI or know about HTTP concerns.
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk

logger = logging.getLogger(__name__)


async def bulk_create_chunks(
    db: AsyncSession,
    chunks: List[Dict[str, Any]],
) -> List[Chunk]:
    """
    Batch-insert multiple Chunk rows and return the created ORM instances.

    Args:
        db:     Active async session.
        chunks: List of dicts with keys matching Chunk column names.

    Returns:
        List of created Chunk ORM instances (with auto-generated UUIDs).
    """
    chunk_objects = [Chunk(**c) for c in chunks]
    db.add_all(chunk_objects)
    await db.flush()
    for c in chunk_objects:
        await db.refresh(c)
    logger.info("Bulk created %d chunk rows.", len(chunk_objects))
    return chunk_objects


async def get_chunks_by_job_id(
    db: AsyncSession,
    job_id: UUID,
) -> List[Chunk]:
    """Retrieve all chunks belonging to a chunking job, ordered by chunk_index."""
    result = await db.execute(
        select(Chunk)
        .where(Chunk.job_id == job_id)
        .order_by(Chunk.chunk_index)
    )
    return list(result.scalars().all())


async def get_chunks_by_ids(
    db: AsyncSession,
    chunk_ids: List[UUID],
) -> List[Chunk]:
    """Retrieve specific chunks by their primary key UUIDs."""
    if not chunk_ids:
        return []
    result = await db.execute(
        select(Chunk).where(Chunk.id.in_(chunk_ids))
    )
    return list(result.scalars().all())


async def bulk_update_chunk_status(
    db: AsyncSession,
    chunk_ids: List[UUID],
    status: str,
    error: Optional[str] = None,
    embedding_model: Optional[str] = None,
    vector_collection: Optional[str] = None,
) -> None:
    """
    Batch-update status (and optional fields) for a list of chunk IDs.

    Args:
        db:               Active async session.
        chunk_ids:        UUIDs of the chunks to update.
        status:           New ChunkStatus value.
        error:            Error detail (set when status='failed').
        embedding_model:  HF model name used for embedding (when known).
        vector_collection: Qdrant collection name (when vector store is done).
    """
    if not chunk_ids:
        return

    values: Dict[str, Any] = {"status": status}
    if error is not None:
        values["error"] = error
    if embedding_model is not None:
        values["embedding_model"] = embedding_model
    if vector_collection is not None:
        values["vector_collection"] = vector_collection

    await db.execute(
        update(Chunk)
        .where(Chunk.id.in_(chunk_ids))
        .values(**values)
    )
    logger.debug(
        "Updated %d chunks → status=%r", len(chunk_ids), status
    )
