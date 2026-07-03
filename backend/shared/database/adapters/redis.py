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
        """Create Redis connection pool and verify connectivity with 3 reattempts."""
        import asyncio
        import redis.asyncio as aioredis
        from redis.exceptions import ConnectionError, TimeoutError
        from shared.config.settings import settings

        max_attempts = 4  # 1 initial + 3 reattempts
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "RedisAdapter: connecting to %s (attempt %d/%d)...",
                    settings.redis_url,
                    attempt,
                    max_attempts - 1,
                )
                self._client = aioredis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    max_connections=10,
                    health_check_interval=30,
                    socket_connect_timeout=10,
                    socket_timeout=10,
                )
                # Verify connectivity
                await self._client.ping()
                logger.info("RedisAdapter: connected.")
                return
            except (ConnectionError, TimeoutError) as exc:
                logger.warning(
                    "RedisAdapter: connection attempt %d failed: %s", attempt, exc
                )
                if attempt == max_attempts:
                    logger.error("RedisAdapter: all connection attempts failed.")
                    raise RuntimeError(
                        f"Failed to connect to Redis after 3 reattempts: {exc}"
                    )
                # Wait 2 seconds before retrying
                await asyncio.sleep(2)

    async def disconnect(self) -> None:
        """Close all Redis connections in the pool."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("RedisAdapter: disconnected.")

    async def health_check(self) -> bool:
        """Send PING and verify PONG response."""
        if not self._client:
            return False
        try:
            return await self._client.ping()
        except Exception as exc:
            logger.warning("RedisAdapter health check failed: %s", exc)
            return False

    @property
    def client(self):
        """Expose raw redis.asyncio.Redis client for direct commands."""
        if not self._client:
            raise RuntimeError("RedisAdapter not connected — call connect() first.")
        return self._client

