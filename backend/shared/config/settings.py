"""
shared.config.settings — Global application settings.

Single pydantic-settings BaseSettings class covering all environment
variables for database connections, Keycloak, Redis, Vault, Qdrant,
and service ports. Loaded once at startup and injected via dependency.

Usage:
    from shared.config.settings import settings
    print(settings.KEYCLOAK_SERVER_URL)
"""
import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Keycloak ──────────────────────────────────────────────────────────────
    KEYCLOAK_SERVER_URL: str = Field(default="http://localhost:8080/")
    KEYCLOAK_INTERNAL_URL: str = Field(default="http://keycloak:8080/")
    KEYCLOAK_ADMIN_USER: str = Field(default="admin")
    KEYCLOAK_ADMIN_PASSWORD: str = Field(default="admin")
    VERIFY_ISSUER: bool = Field(default=False)

    # ── JWT Authentication ─────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = Field(default="secret-key-change-in-production")
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    DB_HOST: str = Field(default="localhost")
    DB_PORT: int = Field(default=5432)
    DB_DATABASE: str = Field(default="keycloak")
    DB_USERNAME: str = Field(default="keycloak")
    DB_PASSWORD: str = Field(default="keycloak_password")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_USERNAME}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_DATABASE}"
        )

    @property
    def database_url_sync(self) -> str:
        """Synchronous URL for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.DB_USERNAME}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_DATABASE}"
        )

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"

    # ── Vault ─────────────────────────────────────────────────────────────────
    VAULT_ADDR: str = Field(default="http://localhost:8200")
    VAULT_TOKEN: str = Field(default="")

    # ── Qdrant (Vector Store) ─────────────────────────────────────────────────
    QDRANT_HOST: str = Field(default="localhost")
    QDRANT_PORT: int = Field(default=6333)

    # ── MinIO (Object Storage) ────────────────────────────────────────────────
    MINIO_ENDPOINT: str = Field(default="minio:9000")
    MINIO_EXTERNAL_ENDPOINT: str = Field(default="localhost:9000")
    MINIO_ROOT_USER: str = Field(default="admin")
    MINIO_ROOT_PASSWORD: str = Field(default="minio_password")
    MINIO_BUCKET: str = Field(default="rag-documents")
    MINIO_SECURE: bool = Field(default=False)

    # ── File Upload ───────────────────────────────────────────────────────────
    MAX_FILE_SIZE_MB: int = Field(default=20)


    # ── LLM Service ───────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = Field(default="")
    LLM_SESSION_TTL_SECONDS: int = Field(default=3600)       # 1 hour sliding TTL
    LLM_MAX_HISTORY_MESSAGES: int = Field(default=50)        # rolling window cap
    LLM_SERVICE_PORT: int = Field(default=8003)

    # ── Service Ports ─────────────────────────────────────────────────────────
    FASTAPI_PORT: int = Field(default=8000)
    RAG_SERVICE_PORT: int = Field(default=8001)
    TOOLS_SERVICE_PORT: int = Field(default=8002)

    # ── Environment ───────────────────────────────────────────────────────────
    ENVIRONMENT: str = Field(default="development")
    SERVICE_NAME: str = Field(default="backend")
    LOG_LEVEL: str = Field(default="INFO")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def keycloak_url(self) -> str:
        """Returns internal Docker URL when running in container, else external."""
        return self.KEYCLOAK_SERVER_URL


settings = Settings()
