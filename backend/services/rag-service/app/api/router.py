"""
app.api.router — Central API router for the RAG service.

Aggregates all endpoint routers. Tag ordering determines Swagger UI layout.
"""
from fastapi import APIRouter

from app.api.endpoints import health, data_sources

api_router = APIRouter()

# Health and status endpoints
api_router.include_router(health.router)

# Data ingestion endpoints
api_router.include_router(data_sources.router, prefix="/api")
