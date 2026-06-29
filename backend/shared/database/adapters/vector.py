"""
shared.database.adapters.vector — Qdrant vector store adapter.

Wraps the qdrant-client AsyncQdrantClient, providing a consistent
lifecycle interface alongside other infrastructure adapters.

Usage:
    from shared.database.adapters.vector import QdrantAdapter
    server_manager.register("qdrant", QdrantAdapter())
"""
import logging

from shared.database.base import DatabaseAdapter

logger = logging.getLogger(__name__)


class QdrantAdapter(DatabaseAdapter):
    """Qdrant vector store adapter using qdrant-client async client."""

    def __init__(self) -> None:
        self._client = None

    async def connect(self) -> None:
        """Initialise AsyncQdrantClient and verify connectivity."""
        # TODO: Implement using qdrant_client.AsyncQdrantClient
        logger.info("QdrantAdapter: connecting...")

    async def disconnect(self) -> None:
        """Close the Qdrant client connection."""
        if self._client:
            # TODO: await self._client.close()
            logger.info("QdrantAdapter: disconnected.")

    async def health_check(self) -> bool:
        """Ping the Qdrant server to verify health."""
        # TODO: Implement qdrant health check
        return True

    @property
    def client(self):
        """Expose the raw AsyncQdrantClient for collection operations."""
        if not self._client:
            raise RuntimeError("QdrantAdapter not connected — call connect() first.")
        return self._client
