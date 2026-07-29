"""
llm-service app.core.lifespan — Application lifespan handler.

Registers Redis adapter with the shared ServerManager singleton.
Redis is the only infrastructure dependency for this service —
it stores session chat history (JSON blobs with TTL).

To add a new adapter:
    1. Instantiate it here
    2. Call server_manager.register("name", adapter)
    3. Done — it will be auto-connected/disconnected on app start/stop.
"""
import logging

from shared.database import server_manager
from shared.database.adapters.redis import RedisAdapter   # direct import — avoids eager loading of Postgres/Qdrant/Vault adapters

logger = logging.getLogger(__name__)


class LifespanHandler:
    """Wires up Redis adapter and delegates lifecycle to ServerManager."""

    def __init__(self) -> None:
        self._registered = False

    def _register_adapters(self) -> None:
        """Register infrastructure adapters required by the LLM service."""
        if self._registered:
            return

        server_manager.register("redis", RedisAdapter())

        self._registered = True
        logger.info("LLM service: Redis adapter registered with ServerManager.")

    async def startup(self) -> None:
        """Called on FastAPI startup — connect all adapters."""
        logger.info("LLM service starting up...")
        self._register_adapters()
        await server_manager.startup()
        logger.info("LLM service startup complete.")

    async def shutdown(self) -> None:
        """Called on FastAPI shutdown — disconnect all adapters cleanly."""
        logger.info("LLM service shutting down...")
        await server_manager.shutdown()
        logger.info("LLM service shutdown complete.")


lifespan_handler = LifespanHandler()
