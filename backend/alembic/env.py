"""
Alembic env.py — migration environment.

Discovers all SQLAlchemy models from backend/app/models/tables/
and any service that adds its models here. Uses synchronous
database URL from shared.config.settings for migration runs.

To run migrations:
    cd backend/
    alembic upgrade head

To generate a new migration:
    alembic revision --autogenerate -m "description"

For services that need tables, they add their version files to:
    backend/services/{service-name}/alembic/versions/
and their models are imported here so autogenerate can detect them.
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Path setup ────────────────────────────────────────────────────────────────
# Ensure backend/ is on sys.path so `from shared...` and `from app...` work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Import shared Base and all ORM models for autogenerate ───────────────────
from shared.database.utils.pool import Base  # noqa: F401
from shared.config.settings import settings

# Import all table models so Alembic can detect them
# Add service model imports here when services need tables:
# from services.rag_service.app.models.tables import *  # noqa: F401
import app.models.tables  # noqa: F401

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with value from shared settings
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection needed)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connects to the DB)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
