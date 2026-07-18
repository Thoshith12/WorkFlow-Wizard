"""
app.pipeline.chunking.strategies — Five text chunking strategy implementations.

Each strategy function accepts a list of preprocessed page dicts and a
strategy-specific config dict, and returns a list of ChunkResult objects.

ChunkResult fields:
    chunk_text:    The text content of the chunk.
    page_number:   Source document page number.
    local_index:   Index within this document (0-based); re-indexed globally
                   at finalize time across all documents in the job.
    metadata:      Extra dict preserved for Qdrant payload.
    is_parent:     True for parent-tier chunks in parent_child strategy.
    parent_index:  local_index of the parent chunk (for child chunks).

All strategies produce chunks from the "content" field of each page dict
(format: [{"page_number": int, "content": str}, ...]) written by the
preprocessing pipeline to Redis.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── ChunkResult dataclass ─────────────────────────────────────────────────────

@dataclass
class ChunkResult:
    """Represents a single text chunk produced by any chunking strategy."""
    chunk_text:   str
    page_number:  int
    local_index:  int
    metadata:     Dict[str, Any] = field(default_factory=dict)
    is_parent:    bool = False
    parent_index: Optional[int] = None


# ── Helper: build LangChain documents from pages ──────────────────────────────

def _pages_to_lc_docs(pages: List[Dict]) -> List[Any]:
    """Convert preprocessed page dicts to LangChain Document objects."""
    from langchain_core.documents import Document
    return [
        Document(
            page_content=p["content"],
            metadata={"page_number": p["page_number"]},
        )
        for p in pages
        if p.get("content", "").strip()
    ]


# ── Strategy 1: Fixed-size character splitting ────────────────────────────────

def chunk_fixed(
    pages: List[Dict],
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> List[ChunkResult]:
    """
    Split pages into fixed character-count chunks with overlap.
    Uses LangChain CharacterTextSplitter with separator="" so it never
    avoids hard cuts regardless of content structure.
    """
    from langchain_text_splitters import CharacterTextSplitter

    splitter = CharacterTextSplitter(
        separator="",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    results: List[ChunkResult] = []
    idx = 0
    for page in pages:
        content = page.get("content", "").strip()
        if not content:
            continue
        page_num = page["page_number"]
        for chunk_text in splitter.split_text(content):
            if chunk_text.strip():
                results.append(
                    ChunkResult(
                        chunk_text=chunk_text,
                        page_number=page_num,
                        local_index=idx,
                    )
                )
                idx += 1
    logger.debug("chunk_fixed: produced %d chunks.", len(results))
    return results


# ── Strategy 2: Recursive character splitting ─────────────────────────────────

def chunk_recursive(
    pages: List[Dict],
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    separators: Optional[List[str]] = None,
) -> List[ChunkResult]:
    """
    Split pages using LangChain RecursiveCharacterTextSplitter.
    Tries each separator in order, falling back to the next if the resulting
    chunks are still too large.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    if separators is None:
        separators = ["\n\n", "\n", ".", " ", ""]

    splitter = RecursiveCharacterTextSplitter(
        separators=separators,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    results: List[ChunkResult] = []
    idx = 0
    for page in pages:
        content = page.get("content", "").strip()
        if not content:
            continue
        page_num = page["page_number"]
        for chunk_text in splitter.split_text(content):
            if chunk_text.strip():
                results.append(
                    ChunkResult(
                        chunk_text=chunk_text,
                        page_number=page_num,
                        local_index=idx,
                    )
                )
                idx += 1
    logger.debug("chunk_recursive: produced %d chunks.", len(results))
    return results


# ── Strategy 3: Semantic (embedding-based) splitting ─────────────────────────

def chunk_semantic(
    pages: List[Dict],
    breakpoint_threshold: float = 0.3,
    min_chunk_size: int = 100,
    embedding_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
) -> List[ChunkResult]:
    """
    Split pages based on semantic similarity between sentences.
    Uses LangChain SemanticChunker with a cosine distance threshold.

    Args:
        pages:                 Preprocessed page dicts.
        breakpoint_threshold:  Cosine distance above which a boundary is added.
        min_chunk_size:        Minimum characters per semantic chunk.
        embedding_fn:          Optional callable(texts) → vectors. If None,
                               falls back to all-MiniLM-L6-v2 for boundary detection.
    """
    from langchain_text_splitters import SemanticChunker
    from langchain_community.embeddings import HuggingFaceEmbeddings

    if embedding_fn is None:
        # Lightweight fallback — not persisted, used only for boundary detection
        lc_embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
        )
    else:
        # Wrap the adapter callable in a LangChain-compatible embeddings class
        class _AdapterEmbeddings:
            def embed_documents(self, texts: List[str]) -> List[List[float]]:
                return embedding_fn(texts)
            def embed_query(self, text: str) -> List[float]:
                return embedding_fn([text])[0]

        lc_embeddings = _AdapterEmbeddings()

    chunker = SemanticChunker(
        embeddings=lc_embeddings,
        breakpoint_threshold_type="gradient",
        breakpoint_threshold_amount=breakpoint_threshold,
    )

    results: List[ChunkResult] = []
    idx = 0
    for page in pages:
        content = page.get("content", "").strip()
        if not content:
            continue
        page_num = page["page_number"]
        docs = chunker.create_documents([content])
        for doc in docs:
            text = doc.page_content.strip()
            if text and len(text) >= min_chunk_size:
                results.append(
                    ChunkResult(
                        chunk_text=text,
                        page_number=page_num,
                        local_index=idx,
                    )
                )
                idx += 1
    logger.debug("chunk_semantic: produced %d chunks.", len(results))
    return results


# ── Strategy 4: Parent-child splitting ───────────────────────────────────────

def chunk_parent_child(
    pages: List[Dict],
    parent_chunk_size: int = 2048,
    child_chunk_size: int = 512,
    overlap: int = 50,
) -> List[ChunkResult]:
    """
    Two-pass split: coarse parent chunks first, then finer child chunks.
    Both parents and children are returned. Parent chunks have is_parent=True.
    Each child chunk carries the local_index of its parent in parent_index.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=parent_chunk_size,
        chunk_overlap=overlap,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=child_chunk_size,
        chunk_overlap=overlap,
    )

    results: List[ChunkResult] = []
    idx = 0
    for page in pages:
        content = page.get("content", "").strip()
        if not content:
            continue
        page_num = page["page_number"]
        parents = parent_splitter.split_text(content)
        for parent_text in parents:
            if not parent_text.strip():
                continue
            parent_idx = idx
            results.append(
                ChunkResult(
                    chunk_text=parent_text,
                    page_number=page_num,
                    local_index=parent_idx,
                    is_parent=True,
                )
            )
            idx += 1
            children = child_splitter.split_text(parent_text)
            for child_text in children:
                if child_text.strip():
                    results.append(
                        ChunkResult(
                            chunk_text=child_text,
                            page_number=page_num,
                            local_index=idx,
                            is_parent=False,
                            parent_index=parent_idx,
                        )
                    )
                    idx += 1
    logger.debug(
        "chunk_parent_child: produced %d total chunks (%d parents).",
        len(results),
        sum(1 for r in results if r.is_parent),
    )
    return results


# ── Strategy 5: Agentic chunking (Claude Haiku 4.5) ──────────────────────────

def chunk_agentic(
    pages: List[Dict],
    system_prompt: str,
    max_chunk_size: int = 800,
    min_chunk_size: int = 100,
) -> List[ChunkResult]:
    """
    LLM-driven chunking using Claude Haiku 4.5 (Anthropic).

    For each page, sends the full page content to Claude with the given
    system_prompt and asks it to return a JSON array of chunk strings.
    Falls back to recursive splitting if the LLM call fails or returns
    non-JSON output.

    Requires ANTHROPIC_API_KEY to be set in the environment.
    """
    import json
    import os
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set — agentic chunking falling back to recursive split."
        )
        return chunk_recursive(pages, chunk_size=max_chunk_size, chunk_overlap=50)

    client = Anthropic(api_key=api_key)

    results: List[ChunkResult] = []
    idx = 0

    for page in pages:
        content = page.get("content", "").strip()
        if not content:
            continue
        page_num = page["page_number"]

        user_message = (
            f"Split the following text into self-contained chunks. "
            f"Target maximum chunk size: {max_chunk_size} characters. "
            f"Minimum chunk size: {min_chunk_size} characters.\n\n"
            f"Text:\n{content}\n\n"
            f"Return ONLY a valid JSON array of strings."
        )

        try:
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            raw = response.content[0].text.strip()

            # Strip accidental markdown fencing
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            chunks_list: List[str] = json.loads(raw)
            if not isinstance(chunks_list, list):
                raise ValueError("LLM response was not a JSON array.")

            for chunk_text in chunks_list:
                chunk_text = str(chunk_text).strip()
                if len(chunk_text) >= min_chunk_size:
                    results.append(
                        ChunkResult(
                            chunk_text=chunk_text,
                            page_number=page_num,
                            local_index=idx,
                            metadata={"strategy": "agentic"},
                        )
                    )
                    idx += 1

            logger.debug(
                "chunk_agentic: page %d produced %d chunks via Claude.",
                page_num, len(chunks_list),
            )

        except Exception as exc:
            logger.warning(
                "chunk_agentic: Claude call failed for page %d (%s) — "
                "falling back to recursive split for this page.",
                page_num, exc,
            )
            # Fallback: recursive split for this individual page
            fallback = chunk_recursive(
                [page], chunk_size=max_chunk_size, chunk_overlap=50
            )
            for cr in fallback:
                cr.local_index = idx
                results.append(cr)
                idx += 1

    logger.debug("chunk_agentic: produced %d chunks total.", len(results))
    return results
