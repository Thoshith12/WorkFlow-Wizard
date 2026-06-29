"""
app.core.lifespan — Application lifespan handler.

Registers all infrastructure adapters with the ServerManager singleton
and delegates startup/shutdown to it. This is the single place where
all database/infrastructure connections are declared for this service.

To add a new adapter:
    1. Instantiate it here
    2. Call server_manager.register("name", adapter)
    3. Done — it will be auto-connected/disconnected on app start/stop.
"""
import logging

from shared.database import server_manager
from shared.database.adapters import (
    PostgresAdapter,
    QdrantAdapter,
    RedisAdapter,
    VaultAdapter,
)
from shared.config.settings import settings

logger = logging.getLogger(__name__)


class LifespanHandler:
    """Wires up adapters and delegates to ServerManager."""

    def __init__(self) -> None:
        self._registered = False

    def _register_adapters(self) -> None:
        """Register all infrastructure adapters for this service."""
        if self._registered:
            return

        server_manager.register("postgres", PostgresAdapter())
        server_manager.register("redis", RedisAdapter())
        server_manager.register("qdrant", QdrantAdapter())
        server_manager.register("vault", VaultAdapter())

        self._registered = True
        logger.info("All adapters registered with ServerManager.")

    async def startup(self) -> None:
        """Called on FastAPI startup — connect all adapters."""
        logger.info("Backend service starting up...")
        self._register_adapters()
        await server_manager.startup()
        logger.info("Backend service startup complete.")

    async def shutdown(self) -> None:
        """Called on FastAPI shutdown — disconnect all adapters cleanly."""
        logger.info("Backend service shutting down...")
        await server_manager.shutdown()
        logger.info("Backend service shutdown complete.")


lifespan_handler = LifespanHandler()
