"""
llm-service app.schemas.chat — Pydantic request/response schemas.

ChatRequest  — inbound payload; includes optional session_id and
               fully optional RequestContext for ephemeral per-turn data.
ChatResponse — outbound payload; always includes session_id for the caller
               to persist and reuse across turns.

RequestContext and its sub-models (RAGChunk, ToolResult, UserMetadata)
are ephemeral — they are used to build a context block that is injected
into the LLM call but are NEVER persisted in Redis session history.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Context sub-models ─────────────────────────────────────────────────────────

class RAGChunk(BaseModel):
    """A single retrieved document chunk from a vector store (e.g. Qdrant)."""

    content: str = Field(..., description="The text content of the retrieved chunk.")
    source: str | None = Field(
        default=None,
        description="Origin of the chunk — filename, URL, document ID, etc.",
    )
    score: float | None = Field(
        default=None,
        description="Similarity/relevance score returned by the vector store.",
    )


class ToolResult(BaseModel):
    """Output returned by a tool invocation (e.g. web_search, code_executor)."""

    tool_name: str = Field(..., description="Name of the tool that produced this result.")
    result: str = Field(..., description="Stringified output from the tool.")


class UserMetadata(BaseModel):
    """
    Caller-supplied user/session metadata injected into every LLM turn.
    Useful for personalising responses without polluting the chat history.
    """

    name: str | None = Field(default=None, description="Display name of the user.")
    role: str | None = Field(
        default=None,
        description="User role or persona (e.g. 'admin', 'developer', 'analyst').",
    )
    preferences: dict[str, str] = Field(
        default_factory=dict,
        description="Arbitrary key-value preference pairs (e.g. {'language': 'French'}).",
    )


class RequestContext(BaseModel):
    """
    Ephemeral, per-request context injected into the LLM call.

    All fields are optional — include only those relevant to the current turn.
    IMPORTANT: context is NEVER stored in Redis session history.
    The caller must re-supply relevant context on every request where it matters.
    """

    rag_chunks: list[RAGChunk] = Field(
        default_factory=list,
        description="Retrieved document snippets from a vector store.",
    )
    tool_results: list[ToolResult] = Field(
        default_factory=list,
        description="Outputs from tool invocations made before this turn.",
    )
    user_metadata: UserMetadata | None = Field(
        default=None,
        description="User profile information to personalise the response.",
    )
    free_text: str | None = Field(
        default=None,
        description="Any additional free-form context string.",
    )


# ── Main request/response schemas ──────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Inbound chat completion request."""

    session_id: str | None = Field(
        default=None,
        description=(
            "Existing session ID to continue a conversation. "
            "Omit (or pass null) to start a new session — the response will "
            "include a fresh session_id to persist for subsequent turns."
        ),
    )
    model: str = Field(
        ...,
        description=(
            "LLM model identifier to route to. "
            "Claude models: 'claude-opus-4-5', 'claude-sonnet-4-5', etc."
        ),
    )
    system_prompt: str = Field(
        ...,
        description=(
            "System prompt injected on every call. "
            "Not stored in session history — the caller controls it per-request."
        ),
    )
    user_message: str = Field(
        ...,
        description="The new user message for this turn.",
    )
    context: RequestContext = Field(
        default_factory=RequestContext,
        description=(
            "Ephemeral per-request context (RAG, tool results, user metadata, "
            "free-form text). Injected before the user message but NOT stored "
            "in session history."
        ),
    )


class ChatResponse(BaseModel):
    """Outbound chat completion response."""

    session_id: str = Field(
        ...,
        description=(
            "Session ID — echoed from the request or newly created. "
            "The caller MUST persist this and include it in all follow-up requests."
        ),
    )
    assistant_message: str = Field(
        ...,
        description="The assistant's reply for this turn.",
    )
    model: str = Field(..., description="The model that produced this response.")
    usage: dict[str, Any] = Field(
        default_factory=dict,
        description="Token usage reported by the provider (input_tokens, output_tokens).",
    )
