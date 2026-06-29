"""
shared.database.server_manager — Central adapter registry & lifecycle manager.

ServerManager acts as the single point of truth for all infrastructure
connections. It is called during FastAPI's lifespan to:
  1. startup()  — connect all registered adapters in registration order
  2. shutdown() — disconnect all adapters in reverse order
  3. health()   — run health checks on all adapters

Usage (in lifespan):
    from shared.database import server_manager
    from shared.database.adapters.postgres import PostgresAdapter

    server_manager.register("postgres", PostgresAdapter())
    server_manager.register("redis", RedisAdapter())

    @asynccontextmanager
    async def lifespan(app):
        await server_manager.startup()
        yield
        await server_manager.shutdown()

Retrieve an adapter anywhere:
    pg = server_manager.get("postgres")
"""
import logging
from typing import Dict

from shared.database.base import DatabaseAdapter

logger = logging.getLogger(__name__)


class ServerManager:
    """Central registry that manages all database/infrastructure adapter lifecycles."""

    def __init__(self) -> None:
        self._adapters: Dict[str, DatabaseAdapter] = {}

    def register(self, name: str, adapter: DatabaseAdapter) -> None:
        """
        Register a named adapter.

        Args:
            name:    Logical name (e.g. "postgres", "redis", "qdrant", "vault")
            adapter: An instance of a DatabaseAdapter subclass.
        """
        if name in self._adapters:
            logger.warning("Adapter '%s' is already registered — overwriting.", name)
        self._adapters[name] = adapter
        logger.debug("Adapter '%s' registered.", name)

    async def startup(self) -> None:
        """Connect all registered adapters. Called on application startup."""
        logger.info("ServerManager: starting up %d adapter(s)...", len(self._adapters))
        for name, adapter in self._adapters.items():
            try:
                await adapter.connect()
                logger.info("  ✓ Adapter '%s' connected.", name)
            except Exception as exc:
                logger.error("  ✗ Adapter '%s' failed to connect: %s", name, exc)
                raise

    async def shutdown(self) -> None:
        """Disconnect all registered adapters in reverse order. Called on shutdown."""
        logger.info("ServerManager: shutting down adapters...")
        for name, adapter in reversed(list(self._adapters.items())):
            try:
                await adapter.disconnect()
                logger.info("  ✓ Adapter '%s' disconnected.", name)
            except Exception as exc:
                logger.warning("  ✗ Adapter '%s' failed to disconnect cleanly: %s", name, exc)

    async def health(self) -> Dict[str, bool]:
        """
        Run health checks on all adapters.

        Returns:
            Dict mapping adapter name → health status (True/False).
        """
        results: Dict[str, bool] = {}
        for name, adapter in self._adapters.items():
            try:
                results[name] = await adapter.health_check()
            except Exception as exc:
                logger.warning("Health check failed for adapter '%s': %s", name, exc)
                results[name] = False
        return results

    def get(self, name: str) -> DatabaseAdapter:
        """
        Retrieve a registered adapter by name.

        Args:
            name: The logical name used during register().

        Raises:
            KeyError: If no adapter with that name is registered.
        """
        if name not in self._adapters:
            raise KeyError(f"No adapter registered with name '{name}'")
        return self._adapters[name]


# Singleton — import this instance everywhere
server_manager = ServerManager()
