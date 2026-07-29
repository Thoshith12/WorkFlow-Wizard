"""
llm-service app.models.session — In-memory session data models.

These dataclasses represent the chat session as stored in Redis.
They are NOT SQLAlchemy ORM models — sessions are JSON-serialised and
stored as Redis strings with a TTL.

ChatMessage  — a single turn (user or assistant).
ChatSession  — the full session: ID + ordered message history + timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class ChatMessage:
    """
    A single message turn in the conversation.

    role:    'user' or 'assistant' — matches the Anthropic messages API format.
    content: Raw text content of the message.

    NOTE: Context blocks (RAG chunks, tool results, etc.) are injected into
    the LLM call but are NEVER stored as ChatMessage content — only the
    original user_message and assistant reply are persisted.
    """

    role: Literal["user", "assistant"]
    content: str


@dataclass
class ChatSession:
    """
    A full chat session stored as a Redis JSON blob.

    session_id:  UUID4 string — the stable identifier returned to callers.
    messages:    Ordered list of ChatMessage turns (user/assistant alternating).
    created_at:  UTC timestamp of session creation.
    updated_at:  UTC timestamp of last message append (refreshed on every turn).

    Serialisation/deserialisation is handled by SessionRepository.
    The rolling window cap (LLM_MAX_HISTORY_MESSAGES) is enforced in
    SessionRepository.save_session() before persisting.
    """

    session_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict for Redis storage."""
        return {
            "session_id": self.session_id,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in self.messages
            ],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        """Deserialise from a Redis-stored JSON dict."""
        return cls(
            session_id=data["session_id"],
            messages=[
                ChatMessage(role=m["role"], content=m["content"])
                for m in data.get("messages", [])
            ],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
