"""
llm-service app.services.llm_router — Model-to-adapter routing.

LLMRouter maps a model identifier string to the correct LLMAdapter instance
using prefix matching. Adapters are instantiated lazily (on first use) and
cached for the lifetime of the application.

Supported prefix → adapter mappings:
    "claude-"  → AnthropicAdapter

To add a new provider:
    1. Implement a new concrete LLMAdapter subclass.
    2. Add its model prefix to _ADAPTER_REGISTRY below.
    3. Done — LLMRouter will instantiate and cache it automatically.

Example models:
    "claude-opus-4-5"    → AnthropicAdapter
    "claude-sonnet-4-5"  → AnthropicAdapter
    "claude-haiku-3"     → AnthropicAdapter
"""
from __future__ import annotations

import logging
from typing import Type

from app.adapters.base import LLMAdapter
from app.adapters.anthropic_adapter import AnthropicAdapter
from app.config.settings import llm_settings

logger = logging.getLogger(__name__)


# ── Provider registry ──────────────────────────────────────────────────────────
# Maps model name prefix → (AdapterClass, kwargs_factory)
# kwargs_factory is a callable that returns the constructor kwargs dict.

def _anthropic_kwargs() -> dict:
    return {"api_key": llm_settings.ANTHROPIC_API_KEY}


_ADAPTER_REGISTRY: list[tuple[str, Type[LLMAdapter], callable]] = [
    ("claude-", AnthropicAdapter, _anthropic_kwargs),
    # ("gpt-",     OpenAIAdapter,   _openai_kwargs),    # future
    # ("gemini-",  GeminiAdapter,   _gemini_kwargs),    # future
]


class LLMRouter:
    """
    Routes a model identifier to the correct LLMAdapter instance.

    Adapters are lazily instantiated on first request and cached
    per prefix for the lifetime of the process.
    """

    def __init__(self) -> None:
        self._cache: dict[str, LLMAdapter] = {}

    def get_adapter(self, model: str) -> LLMAdapter:
        """
        Resolve a model string to a cached adapter instance.

        Args:
            model: The model identifier from ChatRequest.model
                   (e.g. "claude-opus-4-5").

        Returns:
            An LLMAdapter instance for the matching provider.

        Raises:
            ValueError: If no registered prefix matches the model string.
        """
        for prefix, adapter_cls, kwargs_factory in _ADAPTER_REGISTRY:
            if model.startswith(prefix):
                if prefix not in self._cache:
                    kwargs = kwargs_factory()
                    self._cache[prefix] = adapter_cls(**kwargs)
                    logger.info(
                        "LLMRouter: instantiated %s for prefix '%s'.",
                        adapter_cls.__name__,
                        prefix,
                    )
                return self._cache[prefix]

        supported = [p for p, _, _ in _ADAPTER_REGISTRY]
        raise ValueError(
            f"No LLM adapter registered for model '{model}'. "
            f"Supported prefixes: {supported}"
        )


# ── Singleton ──────────────────────────────────────────────────────────────────
llm_router = LLMRouter()
