"""
app.api.router — Central API router.

Aggregates all endpoint sub-routers into a single api_router
that is included in main.py. To add a new feature area, import
its router here and include it.
"""
from fastapi import APIRouter

from app.api.endpoints import health, realms, users, auth

api_router = APIRouter()

# ── Authentication & Keycloak Tokens ───────────────────────────────────────────
api_router.include_router(auth.router, prefix="/api")

# ── Health ─────────────────────────────────────────────────────────────────────
api_router.include_router(health.router, tags=["Health"])

# ── Keycloak API ───────────────────────────────────────────────────────────────
api_router.include_router(realms.router, prefix="/api", tags=["Realms"])
api_router.include_router(users.router, prefix="/api", tags=["Users"])
