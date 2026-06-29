"""
shared.database.base — DatabaseAdapter abstract base class.

All database/infrastructure adapters must implement this interface.
This ensures a consistent lifecycle contract (connect, disconnect,
health_check) across Postgres, Redis, Qdrant, Vault, etc.

Usage:
    class MyAdapter(DatabaseAdapter):
        async def connect(self) -> None: ...
        async def disconnect(self) -> None: ...
        async def health_check(self) -> bool: ...
"""
from abc import ABC, abstractmethod


class DatabaseAdapter(ABC):
    """Abstract base class for all infrastructure adapters."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the underlying data store."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close connections and free resources."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verify the adapter is reachable and healthy.

        Returns:
            True if healthy, False otherwise.
        """
        ...
