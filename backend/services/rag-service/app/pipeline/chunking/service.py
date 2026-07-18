"""
app.pipeline.chunking.service — Chunking pipeline orchestration helpers.

Provides stateless functions consumed by Celery tasks:
  - get_preprocessed_pages  : load a document's pages from Redis
  - apply_chunking_strategy : dispatch to the correct strategy function
  - assign_global_indices   : re-index chunks sequentially across all docs
  - resolve_chunk_language  : pick the best language code for a chunk
"""
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from app.pipeline.chunking.strategies import (
    ChunkResult,
    chunk_fixed,
    chunk_recursive,
    chunk_semantic,
    chunk_parent_child,
    chunk_agentic,
)
from app.models.enums.chunking import ChunkingStrategy

logger = logging.getLogger(__name__)


# ── Redis helpers ─────────────────────────────────────────────────────────────

async def get_preprocessed_pages(
    redis_client,
    data_source_id: UUID,
    document_id: UUID,
) -> List[Dict[str, Any]]:
    """
    Load preprocessed pages for a document from Redis.

    Redis key format (written by finalize_preprocessing_task):
        {data_source_id}_{document_id}_preprocessed_text

    Returns:
        List of page dicts: [{"page_number": int, "content": str}, ...]
        Returns an empty list if the key is missing (stale/expired).
    """
    key = f"{data_source_id}_{document_id}_preprocessed_text"
    raw = await redis_client.get(key)
    if raw is None:
        logger.warning(
            "get_preprocessed_pages: Redis key '%s' not found — document may not be preprocessed.",
            key,
        )
        return []
    return json.loads(raw)


# ── Strategy dispatcher ───────────────────────────────────────────────────────

def apply_chunking_strategy(
    pages: List[Dict[str, Any]],
    strategy: ChunkingStrategy,
    config: Dict[str, Any],
    embedding_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
) -> List[ChunkResult]:
    """
    Dispatch pages to the appropriate chunking strategy function.

    Args:
        pages:        Preprocessed page dicts from Redis.
        strategy:     ChunkingStrategy enum value.
        config:       Raw strategy config dict from ChunkingRequest (e.g.
                      recursive_config, agentic_config, etc.).
        embedding_fn: Optional embedding callable for semantic chunking.

    Returns:
        List of ChunkResult objects with local indices (0-based per document).
    """
    if strategy == ChunkingStrategy.FIXED:
        return chunk_fixed(
            pages,
            chunk_size=config.get("chunk_size", 512),
            chunk_overlap=config.get("chunk_overlap", 50),
        )

    if strategy == ChunkingStrategy.RECURSIVE:
        return chunk_recursive(
            pages,
            chunk_size=config.get("chunk_size", 512),
            chunk_overlap=config.get("chunk_overlap", 50),
            separators=config.get("separators", ["\n\n", "\n", ".", " ", ""]),
        )

    if strategy == ChunkingStrategy.SEMANTIC:
        return chunk_semantic(
            pages,
            breakpoint_threshold=config.get("breakpoint_threshold", 0.3),
            min_chunk_size=config.get("min_chunk_size", 100),
            embedding_fn=embedding_fn,
        )

    if strategy == ChunkingStrategy.PARENT_CHILD:
        return chunk_parent_child(
            pages,
            parent_chunk_size=config.get("parent_chunk_size", 2048),
            child_chunk_size=config.get("child_chunk_size", 512),
            overlap=config.get("overlap", 50),
        )

    if strategy == ChunkingStrategy.AGENTIC:
        return chunk_agentic(
            pages,
            system_prompt=config.get("system_prompt", ""),
            max_chunk_size=config.get("max_chunk_size", 800),
            min_chunk_size=config.get("min_chunk_size", 100),
        )

    raise ValueError(f"Unknown chunking strategy: {strategy!r}")


# ── Global index assignment ───────────────────────────────────────────────────

def assign_global_indices(
    chunks_per_doc: Dict[str, List[ChunkResult]],
) -> List[Tuple[str, ChunkResult]]:
    """
    Assign monotonically increasing global chunk_index values across all
    documents in the job.

    Args:
        chunks_per_doc: {document_id_str: [ChunkResult, ...]} — output of
                         apply_chunking_strategy per document.

    Returns:
        Flat list of (document_id_str, ChunkResult) tuples, with each
        ChunkResult's local_index replaced by the global sequential index.
    """
    flat: List[Tuple[str, ChunkResult]] = []
    global_idx = 0
    for doc_id_str, chunks in chunks_per_doc.items():
        for cr in chunks:
            cr.local_index = global_idx
            flat.append((doc_id_str, cr))
            global_idx += 1
    return flat


# ── Language resolution ───────────────────────────────────────────────────────

def resolve_chunk_language(
    doc_languages: List[str],
) -> str:
    """
    Determine the language code to assign to chunks from a document.

    Uses the first language in the document's language_detected list
    (set by the preprocessing pipeline via FastText). Falls back to "en"
    if the list is empty or None.

    Args:
        doc_languages: language_detected JSONB value from document_registry.

    Returns:
        ISO 639-1 two-letter language code string.
    """
    if doc_languages:
        return doc_languages[0]
    return "en"


# ── Main entry point (called from chunking endpoint) ─────────────────────────

async def run_chunking_pipeline(*args, **kwargs):
    """
    Placeholder — chunking is fully task-driven via Celery.
    The API endpoint dispatches chunking_orchestrator_task directly.
    This function exists to satisfy the app.pipeline.__init__ export contract.
    """
    raise NotImplementedError(
        "run_chunking_pipeline is not called directly. "
        "Use the POST /api/data-sources/{id}/chunk endpoint to initiate chunking."
    )
