"""
shared.database.adapters.postgres — PostgreSQL adapter (SQLAlchemy async).

Manages an async SQLAlchemy engine and session factory backed by asyncpg.
The session factory is exposed via the `session_factory` property for use
in repositories and the get_db() FastAPI dependency.

Usage:
    from shared.database.adapters.postgres import PostgresAdapter
    adapter = PostgresAdapter()
    server_manager.register("postgres", adapter)
"""
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shared.config.settings import settings
from shared.database.base import DatabaseAdapter

logger = logging.getLogger(__name__)


class PostgresAdapter(DatabaseAdapter):
    """
    SQLAlchemy async engine adapter for PostgreSQL.

    Lazily initialises the engine on connect() and exposes
    an AsyncSessionLocal factory for repository use.

    Connection pool is tuned for production workloads:
      - pool_size:        Base number of persistent connections.
      - max_overflow:      Extra connections beyond pool_size under load.
      - pool_recycle:      Recycle connections after 30 min to avoid stale sockets.
      - pool_pre_ping:     Verify connection health before checkout.
    """

    def __init__(self) -> None:
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    async def connect(self) -> None:
        """Create async engine with connection pooling and verify connectivity."""
        logger.info("PostgresAdapter: connecting...")

        self._engine = create_async_engine(
            settings.database_url,
            echo=settings.ENVIRONMENT == "development",
            pool_size=5,
            max_overflow=10,
            pool_recycle=1800,
            pool_pre_ping=True,
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Verify connectivity with a lightweight query
        async with self._engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

        logger.info("PostgresAdapter: connected (pool_size=5, max_overflow=10).")

    async def disconnect(self) -> None:
        """Dispose the engine and all pooled connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("PostgresAdapter: disconnected.")

    async def health_check(self) -> bool:
        """Execute a lightweight SELECT 1 to verify database health."""
        if not self._engine:
            return False
        try:
            async with self._engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.warning("PostgresAdapter health check failed: %s", exc)
            return False

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """AsyncSessionLocal factory for use in repositories."""
        if not self._session_factory:
            raise RuntimeError(
                "PostgresAdapter not connected — call connect() first."
            )
        return self._session_factory
