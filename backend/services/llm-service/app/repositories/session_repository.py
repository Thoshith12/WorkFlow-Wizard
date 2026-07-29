"""
llm-service app.repositories.session_repository — Redis session CRUD.

All chat sessions are stored as JSON blobs in Redis under the key:
    chat_session:{session_id}

TTL is reset on every save, implementing a sliding expiry window.
The rolling window cap (LLM_MAX_HISTORY_MESSAGES) is enforced here —
only the most recent N messages are retained before writing to Redis.

Usage:
    repo = SessionRepository()
    session = await repo.create_session()
    session.messages.append(ChatMessage(role="user", content="Hello"))
    await repo.save_session(session)
    loaded = await repo.get_session(session.session_id)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from shared.database import server_manager

from app.config.settings import llm_settings
from app.models.session import ChatMessage, ChatSession

logger = logging.getLogger(__name__)

_KEY_PREFIX = "chat_session:"


def _make_key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


class SessionRepository:
    """
    Redis-backed repository for chat session history.

    All operations are async and use the shared RedisAdapter client
    managed by the ServerManager lifecycle.
    """

    @property
    def _redis(self):
        """Lazily resolve the RedisAdapter client each call."""
        return server_manager.get("redis").client

    async def get_session(self, session_id: str) -> ChatSession | None:
        """
        Load a session from Redis.

        Returns:
            ChatSession if found, None if the key is missing or expired.
        """
        raw = await self._redis.get(_make_key(session_id))
        if raw is None:
            logger.debug("Session not found in Redis: %s", session_id)
            return None
        try:
            data = json.loads(raw)
            session = ChatSession.from_dict(data)
            logger.debug(
                "Loaded session %s with %d messages.", session_id, len(session.messages)
            )
            return session
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Failed to deserialise session %s: %s", session_id, exc)
            return None

    async def save_session(self, session: ChatSession) -> None:
        """
        Persist a session to Redis with a sliding TTL.

        Enforces the rolling window cap: if message count exceeds
        LLM_MAX_HISTORY_MESSAGES, the oldest messages are trimmed
        (keeping the most recent N messages).
        """
        # Enforce rolling window — trim oldest messages if over cap
        cap = llm_settings.LLM_MAX_HISTORY_MESSAGES
        if len(session.messages) > cap:
            trimmed = len(session.messages) - cap
            session.messages = session.messages[trimmed:]
            logger.debug(
                "Session %s trimmed %d old message(s) to stay within cap of %d.",
                session.session_id,
                trimmed,
                cap,
            )

        session.updated_at = datetime.now(timezone.utc)
        payload = json.dumps(session.to_dict(), ensure_ascii=False)

        await self._redis.set(
            _make_key(session.session_id),
            payload,
            ex=llm_settings.LLM_SESSION_TTL_SECONDS,
        )
        logger.debug(
            "Saved session %s (%d messages, TTL=%ds).",
            session.session_id,
            len(session.messages),
            llm_settings.LLM_SESSION_TTL_SECONDS,
        )

    async def create_session(self) -> ChatSession:
        """
        Create a brand-new empty session with a unique UUID4 session_id.

        The session is NOT persisted until save_session() is called.
        """
        session_id = str(uuid.uuid4())
        session = ChatSession(session_id=session_id)
        logger.debug("Created new session: %s", session_id)
        return session

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session from Redis.

        Returns:
            True if the key existed and was deleted, False if it was already gone.
        """
        deleted = await self._redis.delete(_make_key(session_id))
        if deleted:
            logger.info("Deleted session: %s", session_id)
        else:
            logger.debug("Delete called on non-existent session: %s", session_id)
        return bool(deleted)
