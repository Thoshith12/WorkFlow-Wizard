"""
app.repositories.document — Document persistence layer.

All database access for the documents table is encapsulated here.
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

logger = logging.getLogger(__name__)


async def create_document(
    db: AsyncSession,
    *,
    data_source_id: UUID,
    file_name: str,
    status: str = "stored",
    config: Optional[Dict[str, Any]] = None,
) -> Document:
    """
    Insert a new Document row and flush to obtain the generated UUID.

    Args:
        db:             Active async session.
        data_source_id: Parent data source FK.
        file_name:      Original uploaded file name.
        status:         Initial document status (default: 'stored').
        config:         JSONB metadata (storage_path, content_type, size, etc.).

    Returns:
        The newly created Document ORM instance.
    """
    doc = Document(
        data_source_id=data_source_id,
        file_name=file_name,
        status=status,
        config=config or {},
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    logger.info(
        "Created Document id=%s file=%r ds_id=%s",
        doc.id, doc.file_name, doc.data_source_id,
    )
    return doc


async def bulk_create_documents(
    db: AsyncSession,
    documents: List[Dict[str, Any]],
) -> List[Document]:
    """
    Batch-insert multiple Document rows.

    Args:
        db:        Active async session.
        documents: List of dicts with keys matching Document columns.

    Returns:
        List of created Document ORM instances.
    """
    doc_objects = [Document(**doc_data) for doc_data in documents]
    db.add_all(doc_objects)
    await db.flush()
    for doc in doc_objects:
        await db.refresh(doc)
    logger.info("Bulk created %d documents.", len(doc_objects))
    return doc_objects


async def get_documents_by_data_source(
    db: AsyncSession,
    data_source_id: UUID,
) -> List[Document]:
    """Retrieve all documents belonging to a data source."""
    result = await db.execute(
        select(Document)
        .where(Document.data_source_id == data_source_id)
        .order_by(Document.created_at)
    )
    return list(result.scalars().all())
