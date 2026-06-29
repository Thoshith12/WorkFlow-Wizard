"""
shared.database.adapters — Concrete DatabaseAdapter implementations.

Available adapters:
    PostgresAdapter — SQLAlchemy async engine (asyncpg driver)
    QdrantAdapter   — Qdrant vector store (qdrant-client)
    RedisAdapter    — Redis async client (redis-py)
    VaultAdapter    — HashiCorp Vault (hvac)
"""
from shared.database.adapters.postgres import PostgresAdapter
from shared.database.adapters.vector import QdrantAdapter
from shared.database.adapters.redis import RedisAdapter
from shared.database.adapters.vault import VaultAdapter

__all__ = ["PostgresAdapter", "QdrantAdapter", "RedisAdapter", "VaultAdapter"]
