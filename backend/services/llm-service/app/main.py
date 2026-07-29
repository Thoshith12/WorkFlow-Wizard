"""
llm-service app.main — FastAPI application entrypoint.

Initialises the FastAPI instance, registers middleware, wires the
lifespan context manager (Redis startup/shutdown via ServerManager),
and includes the centralised API router.

Endpoints:
    POST /api/llm/chat  — Chat completion with session history.
    GET  /health        — Service liveness probe.
    GET  /docs          — Swagger UI.
    GET  /redoc         — ReDoc UI.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import llm_settings
from app.core.lifespan import lifespan_handler
from app.api.router import api_router

# Configure structured logging before anything else
import logging
logging.basicConfig(
    level=getattr(logging, llm_settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown via ServerManager."""
    await lifespan_handler.startup()
    yield
    await lifespan_handler.shutdown()


# ── OpenAPI tag ordering ───────────────────────────────────────────────────────
OPENAPI_TAGS = [
    {
        "name": "Chat",
        "description": (
            "LLM chat completion with session-based history. "
            "First call creates a session; subsequent calls continue it."
        ),
    },
    {
        "name": "Health",
        "description": "Service liveness and readiness probes.",
    },
]


# ── Application ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="LLM Service",
    description=(
        "LLM routing microservice with session-based chat history.\n\n"
        "Routes requests to the correct LLM provider (Anthropic Claude) "
        "based on the model identifier. Maintains per-session conversation "
        "history in Redis with a 1-hour sliding TTL. "
        "Supports ephemeral per-request context injection (RAG chunks, tool "
        "results, user metadata) that enriches LLM calls without polluting history."
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(api_router)

logger.info(
    "LLM Service initialised. Environment: %s | Port: %d",
    llm_settings.ENVIRONMENT,
    llm_settings.LLM_SERVICE_PORT,
)
