"""
app.core.lifespan — RAG service lifespan handler.

Registers all infrastructure adapters with the shared ServerManager singleton
and delegates startup/shutdown to it. Initializes MinIO target bucket on startup.
"""
import logging

from shared.database import server_manager
from shared.database.adapters import (
    PostgresAdapter,
    RedisAdapter,
    QdrantAdapter,
)

logger = logging.getLogger(__name__)


class LifespanHandler:
    """Wires up adapters and delegates to ServerManager."""

    def __init__(self) -> None:
        self._registered = False

    def _register_adapters(self) -> None:
        """Register infrastructure adapters required by the RAG service."""
        if self._registered:
            return

        server_manager.register("postgres", PostgresAdapter())
        server_manager.register("redis", RedisAdapter())
        server_manager.register("qdrant", QdrantAdapter())

        self._registered = True
        logger.info("RAG service: all adapters registered with ServerManager.")

    async def startup(self) -> None:
        """Called on FastAPI startup — connect all adapters and initialize storage."""
        logger.info("RAG service starting up...")
        self._register_adapters()
        await server_manager.startup()

        # Initialize MinIO target bucket
        try:
            from app.services.minio import minio_client
            await minio_client.ensure_bucket()
        except Exception as exc:
            logger.warning("MinIO bucket initialization failed on startup: %s", exc)

        logger.info("RAG service startup complete.")

    async def shutdown(self) -> None:
        """Called on FastAPI shutdown — disconnect all adapters cleanly."""
        logger.info("RAG service shutting down...")
        await server_manager.shutdown()
        logger.info("RAG service shutdown complete.")


lifespan_handler = LifespanHandler()
