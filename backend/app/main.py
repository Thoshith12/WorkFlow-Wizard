"""
backend.app.main — FastAPI application entrypoint.

Initialises the FastAPI instance, registers middleware, wires the
lifespan context manager (ServerManager startup/shutdown), and
includes the centralised API router.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config.settings import settings
from shared.logging.setup import configure_logging
from app.api.router import api_router
from app.core.lifespan import lifespan_handler

# Configure structured logging on import
configure_logging(
    service_name=settings.SERVICE_NAME,
    level=settings.LOG_LEVEL,
    json_output=settings.ENVIRONMENT != "development",
)

import logging
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown via ServerManager."""
    await lifespan_handler.startup()
    yield
    await lifespan_handler.shutdown()


openapi_tags = [
    {
        "name": "Admin Login",
        "description": "Admin login and custom JWT authentication token issuance.",
    },
    {"name": "Auth", "description": "Keycloak OIDC token management endpoints."},
    {"name": "Realms", "description": "Keycloak realm administration endpoints."},
    {"name": "Users", "description": "Keycloak user management endpoints."},
    {"name": "Health", "description": "System health check endpoints."},
]

app = FastAPI(
    title="Keycloak FastAPI Backend",
    description=(
        "Production-grade FastAPI backend for Keycloak realm, user, "
        "and OIDC token management with microservice architecture."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=openapi_tags,
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(api_router)
