"""
app.api.router — Central API router for the Tools service.

Aggregates all endpoint routers. Tag ordering determines Swagger UI layout.
"""
from fastapi import APIRouter

from app.api.endpoints import health, tools, custom_tools, execution

api_router = APIRouter()

# Health and status endpoints (no auth)
api_router.include_router(health.router)

# Universal tool listing + schema discovery
api_router.include_router(tools.router, prefix="/api")

# Custom tool CRUD (owner-gated)
api_router.include_router(custom_tools.router, prefix="/api")

# Tool execution
api_router.include_router(execution.router, prefix="/api")
