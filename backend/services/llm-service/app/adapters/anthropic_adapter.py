"""
llm-service app.adapters.anthropic_adapter — Anthropic Claude adapter.

Implements LLMAdapter using the official `anthropic` Python SDK
(AsyncAnthropic for non-blocking I/O).

Message construction strategy:
  - All prior history turns (messages[:-1]) are passed as-is.
  - The current user message (messages[-1]) has the context_block
    prepended if one is provided, so context never pollutes history.
  - The system prompt is passed as the top-level `system` parameter
    (Anthropic's preferred approach — not injected into messages).

Supported model families (prefix-matched by LLMRouter):
  - claude-opus-*
  - claude-sonnet-*
  - claude-haiku-*
"""
from __future__ import annotations

import logging

from app.adapters.base import LLMAdapter, LLMAdapterError
from app.models.session import ChatMessage

logger = logging.getLogger(__name__)


class AnthropicAdapter(LLMAdapter):
    """
    Async Anthropic Claude adapter.

    Instantiated once by LLMRouter and reused across requests.
    The underlying AsyncAnthropic client manages its own connection pool.
    """

    def __init__(self, api_key: str) -> None:
        try:
            import anthropic as _anthropic
            self._client = _anthropic.AsyncAnthropic(api_key=api_key)
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package not installed. "
                "Run: pip install anthropic>=0.30.0"
            ) from exc

    async def complete(
        self,
        model: str,
        system_prompt: str,
        messages: list[ChatMessage],
        context_block: str | None = None,
    ) -> tuple[str, dict]:
        """
        Call Anthropic Messages API and return (assistant_text, usage).

        The context_block (if provided) is prepended to the content of the
        latest user message only. Prior history turns are passed verbatim.
        """
        if not messages:
            raise LLMAdapterError("Cannot call LLM with an empty message list.")

        # Build Anthropic-format messages list
        # Prior turns: pass content as-is (already clean — no context bleed)
        anthropic_messages = [
            {"role": m.role, "content": m.content}
            for m in messages[:-1]
        ]

        # Current user turn: optionally prepend context block
        latest_content = messages[-1].content
        if context_block:
            latest_content = f"{context_block}\n\n{latest_content}"
            logger.debug(
                "Context block injected before user message (len=%d chars).",
                len(context_block),
            )

        anthropic_messages.append({"role": "user", "content": latest_content})

        try:
            response = await self._client.messages.create(
                model=model,
                system=system_prompt,
                messages=anthropic_messages,
                max_tokens=4096,
            )
        except Exception as exc:
            logger.error(
                "Anthropic API call failed for model '%s': %s", model, exc
            )
            raise LLMAdapterError(
                f"Anthropic API error for model '{model}': {exc}"
            ) from exc

        # Extract response text — first content block
        if not response.content or not hasattr(response.content[0], "text"):
            raise LLMAdapterError(
                f"Anthropic returned an unexpected content format: {response.content}"
            )

        assistant_text: str = response.content[0].text
        usage: dict = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

        logger.debug(
            "Anthropic '%s' completed. input_tokens=%d, output_tokens=%d.",
            model,
            usage["input_tokens"],
            usage["output_tokens"],
        )

        return assistant_text, usage
