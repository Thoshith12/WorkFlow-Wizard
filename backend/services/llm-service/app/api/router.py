"""
llm-service app.api.router — Central API router.

Aggregates all endpoint sub-routers under the /api/llm prefix.
To add a new endpoint group, import its router here and include it.
"""
from fastapi import APIRouter

from app.api.endpoints import chat

api_router = APIRouter()

# ── Health (inline — lightweight) ─────────────────────────────────────────────
health_router = APIRouter(tags=["Health"])


@health_router.get("/health", summary="Service health check")
async def health() -> dict:
    """Returns service liveness status."""
    return {"status": "ok", "service": "llm-service"}


api_router.include_router(health_router)

# ── Chat completions ───────────────────────────────────────────────────────────
api_router.include_router(chat.router, prefix="/api/llm", tags=["Chat"])
