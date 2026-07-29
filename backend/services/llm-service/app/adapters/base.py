"""
llm-service app.adapters.base — Abstract base class for all LLM providers.

All concrete adapters (Anthropic, OpenAI, Gemini, etc.) must implement
this interface. The LLMRouter uses this ABC for type-safe dispatch.

The complete() method receives:
  - model:          The exact model identifier string.
  - system_prompt:  System instructions (injected as a top-level param
                    where the provider supports it, or as first message).
  - messages:       The full ordered conversation history from Redis
                    (user and assistant turns only — raw content).
  - context_block:  Pre-rendered ephemeral context string built by
                    ContextBuilder. Injected before the latest user
                    message at call time. NOT persisted.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.session import ChatMessage


class LLMAdapterError(Exception):
    """Raised when an LLM provider call fails after all retries."""


class LLMAdapter(ABC):
    """Abstract base for all LLM provider adapters."""

    @abstractmethod
    async def complete(
        self,
        model: str,
        system_prompt: str,
        messages: list[ChatMessage],
        context_block: str | None = None,
    ) -> tuple[str, dict]:
        """
        Call the LLM and return the assistant reply.

        Args:
            model:         Provider-specific model identifier.
            system_prompt: System prompt for this call.
            messages:      Full ordered history (user + assistant turns).
                           The last element is the current user message.
            context_block: Optional pre-rendered context string to prepend
                           to the current user message before sending.
                           NOT included in history persistence.

        Returns:
            A 2-tuple of:
              - assistant_text (str): The model's reply.
              - usage (dict):         Provider token counts, e.g.:
                                      {"input_tokens": 123, "output_tokens": 45}

        Raises:
            LLMAdapterError: On unrecoverable provider API failures.
        """
