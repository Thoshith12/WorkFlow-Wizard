"""
tools-service app.main — Tools microservice FastAPI entrypoint.

Wires together:
  - Lifespan handler (shared ServerManager for Postgres, Redis)
  - Central API router (health probes + tool endpoints)
  - CORS middleware
  - Swagger UI with ordered tags
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config.settings import settings
from shared.logging.setup import configure_logging

from app.core.lifespan import lifespan_handler
from app.api.router import api_router

configure_logging(service_name="tools-service", level=settings.LOG_LEVEL)


# ── Tag metadata for Swagger UI ordering ──────────────────────────────────────
OPENAPI_TAGS = [
    {
        "name": "Tools",
        "description": "Universal tool listing and schema discovery.",
    },
    {
        "name": "Custom Tools",
        "description": "Custom tool CRUD operations (owner-gated).",
    },
    {
        "name": "Execution",
        "description": "Tool execution (system + custom).",
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
    title="Tools Service",
    description=(
        "Unified tool management microservice.\n\n"
        "Provides system tools (LangChain built-ins, in-process) and "
        "user-defined custom tools (sandboxed via gVisor), with JWT-protected "
        "endpoints and standardized schema discovery."
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
