"""
rag-service app.main — RAG microservice FastAPI entrypoint.

Wires together:
  - Lifespan handler (shared ServerManager for Postgres, Redis, Qdrant)
  - Central API router (health probes + data ingestion endpoints)
  - CORS middleware
  - Custom OpenAPI schema (ensures file pickers display cleanly in Swagger UI)
  - Swagger UI with ordered tags
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from shared.config.settings import settings
from shared.logging.setup import configure_logging

from app.core.lifespan import lifespan_handler
from app.api.router import api_router

configure_logging(service_name="rag-service", level=settings.LOG_LEVEL)


# ── Tag metadata for Swagger UI ordering ──────────────────────────────────────
OPENAPI_TAGS = [
    {
        "name": "Data Sources",
        "description": "Data source ingestion and management endpoints.",
    },
    {
        "name": "Chunking",
        "description": "Chunking and embedding pipeline endpoints.",
    },
    {
        "name": "Health",
        "description": "Service liveness and readiness probes.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — delegates to shared LifespanHandler."""
    await lifespan_handler.startup()
    yield
    await lifespan_handler.shutdown()


app = FastAPI(
    title="RAG Service",
    description=(
        "Retrieval-Augmented Generation microservice.\n\n"
        "Handles document ingestion, chunking, embedding, and retrieval."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routes
app.include_router(api_router)


# ── Custom OpenAPI Schema for Swagger UI File Uploads ─────────────────────────
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    # Ensure array file properties render with binary format in Swagger UI
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    for schema in schemas.values():
        if "properties" in schema and "files" in schema["properties"]:
            files_prop = schema["properties"]["files"]
            if files_prop.get("type") == "array" and "items" in files_prop:
                files_prop["items"]["type"] = "string"
                files_prop["items"]["format"] = "binary"
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
