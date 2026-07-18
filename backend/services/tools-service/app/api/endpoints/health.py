"""
app.api.endpoints.health — Tools service health check endpoints.

Exposes liveness and readiness probes that interrogate all registered
infrastructure adapters via the shared ServerManager.
"""
from fastapi import APIRouter

from shared.database import server_manager

router = APIRouter()


@router.get("/", summary="Root", tags=["Health"])
async def root():
    """Welcome endpoint."""
    return {"service": "tools-service", "status": "running"}


@router.get("/health", summary="Liveness probe", tags=["Health"])
async def health():
    """Simple liveness check — returns 200 if process is alive."""
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe", tags=["Health"])
async def readiness():
    """Readiness check — verifies all infrastructure adapters are healthy."""
    adapter_status = await server_manager.health()
    all_healthy = all(adapter_status.values())
    return {
        "status": "ready" if all_healthy else "degraded",
        "adapters": adapter_status,
    }
