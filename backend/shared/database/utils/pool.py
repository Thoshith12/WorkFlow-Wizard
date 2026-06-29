"""
shared.database.utils.pool — Connection pool helpers & async session factory.

Provides get_db() FastAPI dependency that yields an AsyncSession
and the Base declarative model for all SQLAlchemy table definitions.

Usage (in a repository):
    from shared.database.utils.pool import get_db
    async def my_route(db: AsyncSession = Depends(get_db)): ...

Usage (for model definitions):
    from shared.database.utils.pool import Base
    class UserTable(Base):
        __tablename__ = "users"
        ...
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from shared.database import server_manager


class Base(DeclarativeBase):
    """
    Shared declarative base for all SQLAlchemy ORM models.
    All tables across backend/app and services inherit from this.
    """
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an AsyncSession.
    Retrieves the session factory from the ServerManager's PostgresAdapter.

    The session is automatically committed on success and rolled back on error.
    Always closed on exit.

    Usage:
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    postgres = server_manager.get("postgres")
    async with postgres.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
