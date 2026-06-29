"""
shared.database.adapters.redis — Redis adapter (redis-py async).

Wraps redis.asyncio.Redis, providing connection pooling and
a consistent lifecycle interface for the ServerManager.

Usage:
    from shared.database.adapters.redis import RedisAdapter
    server_manager.register("redis", RedisAdapter())
"""
import logging

from shared.database.base import DatabaseAdapter

logger = logging.getLogger(__name__)


class RedisAdapter(DatabaseAdapter):
    """Async Redis adapter backed by redis.asyncio."""

    def __init__(self) -> None:
        self._client = None

    async def connect(self) -> None:
        """Create Redis connection pool and verify connectivity."""
        # TODO: Implement using redis.asyncio.from_url(settings.redis_url)
        logger.info("RedisAdapter: connecting...")

    async def disconnect(self) -> None:
        """Close all Redis connections in the pool."""
        if self._client:
            # TODO: await self._client.aclose()
            logger.info("RedisAdapter: disconnected.")

    async def health_check(self) -> bool:
        """Send PING and verify PONG response."""
        # TODO: Implement PING/PONG check
        return True

    @property
    def client(self):
        """Expose raw redis.asyncio.Redis client for direct commands."""
        if not self._client:
            raise RuntimeError("RedisAdapter not connected — call connect() first.")
        return self._client
