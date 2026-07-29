"""
llm-service app.config.settings — Service-specific settings.

Extends shared settings with LLM-specific environment variables.
All values can be overridden via .env file or environment variables.

Usage:
    from app.config.settings import llm_settings
    print(llm_settings.ANTHROPIC_API_KEY)
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    # ── Anthropic ─────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = Field(default="")

    # ── Session management ────────────────────────────────────────────────────
    LLM_SESSION_TTL_SECONDS: int = Field(default=3600)      # 1 hour
    LLM_MAX_HISTORY_MESSAGES: int = Field(default=50)       # rolling window

    # ── Redis (inherited from env, mirrors shared settings) ───────────────────
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"

    # ── Service ───────────────────────────────────────────────────────────────
    LLM_SERVICE_PORT: int = Field(default=8003)
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


llm_settings = LLMSettings()
