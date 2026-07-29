"""
llm-service app.services.llm_service — Main orchestrator.

LLMService is the single class called by the API endpoint.
It coordinates:
  1. Session load/create (SessionRepository → Redis)
  2. Persistent history update (user message appended)
  3. Ephemeral context rendering (ContextBuilder → context_block)
  4. LLM call dispatch (LLMRouter → concrete adapter)
  5. Persistent history update (assistant reply appended)
  6. Session persistence (back to Redis with sliding TTL)

Separation of concerns:
  - LLMService knows nothing about HTTP — it works with domain objects.
  - SessionRepository owns all Redis I/O.
  - ContextBuilder owns context rendering.
  - LLMRouter owns adapter selection.
  - Adapters own provider-specific API calls.

Exceptions:
  - SessionNotFoundError: raised when session_id is provided but expired/missing.
  - LLMAdapterError:      propagated from the adapter on provider failures.
  - ValueError:           raised by LLMRouter for unknown model prefixes.
"""
from __future__ import annotations

import logging

from app.models.session import ChatMessage
from app.repositories.session_repository import SessionRepository
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.context_builder import ContextBuilder
from app.services.llm_router import llm_router

logger = logging.getLogger(__name__)


class SessionNotFoundError(Exception):
    """Raised when a requested session_id does not exist or has expired."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(
            f"Session '{session_id}' not found. "
            "It may have expired or never existed. "
            "Start a new session by omitting session_id."
        )


class LLMService:
    """
    Main orchestrator for chat completions.

    Dependencies are injected via __init__ to keep the class testable —
    pass mock repositories/builders in unit tests without patching globals.
    """

    def __init__(
        self,
        session_repo: SessionRepository | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self.session_repo = session_repo or SessionRepository()
        self.context_builder = context_builder or ContextBuilder()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        Execute a single chat turn and return the assistant response.

        Flow:
          1. Load existing session from Redis OR create a new empty one.
          2. Append the raw user_message to persistent history.
          3. Render request.context into an ephemeral context_block string.
          4. Route request.model to the correct LLM adapter.
          5. Call the adapter with history + ephemeral context_block.
          6. Append the assistant reply to persistent history.
          7. Save updated history to Redis (with sliding TTL + rolling cap).
          8. Return ChatResponse with session_id + assistant reply.

        Args:
            request: Validated ChatRequest from the API endpoint.

        Returns:
            ChatResponse with session_id (persist this!), assistant reply, and usage.

        Raises:
            SessionNotFoundError: If session_id is given but not found in Redis.
            LLMAdapterError:      If the LLM provider call fails.
            ValueError:           If the model prefix is not registered.
        """
        # ── Step 1: Resolve session ────────────────────────────────────────────
        if request.session_id:
            session = await self.session_repo.get_session(request.session_id)
            if session is None:
                raise SessionNotFoundError(request.session_id)
            logger.info(
                "Continuing session %s (%d existing messages).",
                request.session_id,
                len(session.messages),
            )
        else:
            session = await self.session_repo.create_session()
            logger.info("Started new session %s.", session.session_id)

        # ── Step 2: Append user message to PERSISTENT history ─────────────────
        # Only the raw user_message is stored — context is NOT persisted.
        session.messages.append(
            ChatMessage(role="user", content=request.user_message)
        )

        # ── Step 3: Render ephemeral context block ─────────────────────────────
        context_block = self.context_builder.build(request.context)

        # ── Step 4 & 5: Route and call LLM ────────────────────────────────────
        adapter = llm_router.get_adapter(request.model)
        logger.info(
            "Routing model '%s' via %s.", request.model, type(adapter).__name__
        )

        assistant_text, usage = await adapter.complete(
            model=request.model,
            system_prompt=request.system_prompt,
            messages=session.messages,          # full persistent history
            context_block=context_block,         # ephemeral — NOT stored
        )

        # ── Step 6: Append assistant reply to PERSISTENT history ───────────────
        session.messages.append(
            ChatMessage(role="assistant", content=assistant_text)
        )

        # ── Step 7: Persist updated session ───────────────────────────────────
        # save_session() enforces the rolling window cap before writing.
        await self.session_repo.save_session(session)
        logger.info(
            "Session %s saved. History length: %d messages.",
            session.session_id,
            len(session.messages),
        )

        # ── Step 8: Return response ────────────────────────────────────────────
        return ChatResponse(
            session_id=session.session_id,
            assistant_message=assistant_text,
            model=request.model,
            usage=usage,
        )


# ── Module-level singleton (used by the endpoint) ──────────────────────────────
llm_service = LLMService()
