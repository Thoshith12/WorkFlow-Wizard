"""
llm-service app.api.endpoints.chat — Chat completion endpoint.

Exposes:
    POST /api/llm/chat

First call (no session_id):
    → Creates a new session, returns session_id + first reply.

Subsequent calls (with session_id):
    → Loads history from Redis, appends user message, calls LLM,
      persists updated history, returns reply.

Error responses:
    404  — session_id provided but expired or not found.
    422  — invalid request body (Pydantic validation).
    500  — LLM provider failure or unexpected server error.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.adapters.base import LLMAdapterError
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.llm_service import SessionNotFoundError, llm_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chat completion with session history",
    description=(
        "Send a user message to an LLM model. "
        "On the first call, omit `session_id` — a new session is created and "
        "returned in the response. Include `session_id` on all subsequent calls "
        "to continue the conversation with full history. "
        "The optional `context` field (RAG chunks, tool results, user metadata, "
        "free text) is injected per-turn but never stored in session history."
    ),
    responses={
        200: {"description": "Successful chat completion."},
        404: {
            "description": (
                "Session not found — the session_id has expired or never existed. "
                "Start a new session by omitting session_id."
            )
        },
        422: {"description": "Validation error in the request body."},
        500: {"description": "LLM provider failure or internal server error."},
    },
    tags=["Chat"],
)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Execute a single chat turn.

    - First request: omit `session_id` → a new session is created.
    - Follow-up requests: include the `session_id` from the previous response.
    - The `context` field is ephemeral — pass relevant RAG/tool/metadata on each turn.
    """
    try:
        response = await llm_service.chat(request)
        return response

    except SessionNotFoundError as exc:
        logger.warning("Session not found: %s", exc.session_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "session_not_found",
                "message": str(exc),
                "session_id": exc.session_id,
            },
        ) from exc

    except ValueError as exc:
        # Unknown model prefix from LLMRouter
        logger.warning("Invalid model in request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_model", "message": str(exc)},
        ) from exc

    except LLMAdapterError as exc:
        logger.error("LLM adapter error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "llm_provider_error", "message": str(exc)},
        ) from exc

    except Exception as exc:
        logger.exception("Unexpected error in chat endpoint: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "message": "An unexpected error occurred."},
        ) from exc
