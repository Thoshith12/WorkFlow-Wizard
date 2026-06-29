"""
app.api.endpoints.health — Health check endpoints.

GET /        — Root welcome endpoint
GET /health  — Liveness probe (returns {"status": "healthy"})
GET /health/ready — Readiness probe (checks all adapters via ServerManager)
"""
from fastapi import APIRouter

from shared.database import server_manager

router = APIRouter()


@router.get("/", summary="Root")
async def root():
    """Welcome endpoint."""
    return {
        "message": "Keycloak FastAPI Backend is running.",
        "docs": "/docs",
        "status": "online",
    }


@router.get("/health", summary="Liveness probe")
async def health():
    """Simple liveness check — returns 200 if process is alive."""
    return {"status": "healthy"}


@router.get("/health/ready", summary="Readiness probe")
async def readiness():
    """Readiness check — verifies all infrastructure adapters are healthy."""
    adapter_health = await server_manager.health()
    all_healthy = all(adapter_health.values())
    return {
        "status": "ready" if all_healthy else "degraded",
        "adapters": adapter_health,
    }
