"""
app.models.enums.chunking — Enumerations for the chunking & embedding pipeline.

Defines:
    ChunkingStrategy — the five supported text chunking strategies.
    EmbeddingMode    — how vectors are stored in Qdrant (dense / hybrid / sparse).
    ChunkStatus      — lifecycle states a chunk row moves through in chunk_registry.
"""
from enum import Enum


class ChunkingStrategy(str, Enum):
    """
    Text chunking strategies supported by the pipeline.

    - FIXED:        Split by fixed character/token count with overlap.
    - RECURSIVE:    LangChain RecursiveCharacterTextSplitter; tries separator
                    hierarchy (\n\n → \n → . → space → "") before hard split.
    - SEMANTIC:     Embedding-based breakpoint detection; splits where semantic
                    similarity drops below a threshold.
    - PARENT_CHILD: Two-pass split — large parent chunks first, then finer child
                    chunks; both stored with a parent_chunk_index FK reference.
    - AGENTIC:      LLM (Claude Haiku 4.5) decides where to split based on
                    semantic coherence; accepts a configurable system prompt.
    """

    FIXED        = "fixed"
    RECURSIVE    = "recursive"
    SEMANTIC     = "semantic"
    PARENT_CHILD = "parent_child"
    AGENTIC      = "agentic"


class EmbeddingMode(str, Enum):
    """
    Qdrant vector storage mode.

    - DENSE:   Only dense float vectors (cosine similarity).
    - HYBRID:  Dense vectors + Qdrant built-in BM25 sparse vectors.
    - SPARSE:  Qdrant built-in BM25 sparse vectors only (keyword-based retrieval).
    """

    DENSE  = "dense"
    HYBRID = "hybrid"
    SPARSE = "sparse"


class ChunkStatus(str, Enum):
    """
    Lifecycle status values written to chunk_registry.status.

    Transitions:
        INITIATED
          → CHUNKING (when chunk_page_batch_task picks up the pages)
          → EMBEDDING (when embed_chunk_batch_task begins encoding)
          → EMBEDDINGS_GENERATED (encoding done, vector not yet in Qdrant)
          → VECTOR_STORE_SUCCESSFUL (upserted to Qdrant collection)
          → FAILED (any stage — error column holds the reason)
    """

    INITIATED               = "initiated"
    CHUNKING                = "chunking"
    EMBEDDING               = "embedding"
    EMBEDDINGS_GENERATED    = "embeddings_generated"
    VECTOR_STORE_SUCCESSFUL = "vector_store_successful"
    FAILED                  = "failed"
