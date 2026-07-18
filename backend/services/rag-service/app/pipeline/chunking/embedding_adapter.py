"""
app.pipeline.chunking.embedding_adapter — HuggingFace embedding adapter.

Responsibilities:
  1. Loads embedding_models.yaml at module init to build a model registry.
  2. Detects the best available compute device once at import time
     (NVIDIA CUDA → Apple MPS → Intel XPU → CPU).
  3. Loads SentenceTransformer models from the HF disk cache on demand —
     only when actually needed for an embedding job.
  4. Unloads models from VRAM/RAM explicitly when a job finishes, calling
     gc.collect() and the appropriate torch cache-clear, so GPU memory is
     immediately freed for the next job.

Language fallback logic (used by tasks):
    for model_name in user_selected_models:
        supported = get_supported_languages(model_name)
        if "*" in supported or chunk_language in supported:
            embed with this model → break
    else:
        mark chunk FAILED with human-readable error

Thread / process safety:
    The _model_cache dict is module-level and lives inside a single Celery
    worker process. Celery's default prefork concurrency means each worker
    process has its own independent cache — no locking is needed.
"""
import gc
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ── Compute device resolution (done once at module import) ────────────────────

def _resolve_device() -> str:
    """
    Return the best available PyTorch device string in priority order:
        NVIDIA CUDA → Apple MPS → Intel XPU → CPU
    """
    try:
        import torch  # imported lazily to avoid hard requirement at startup

        if torch.cuda.is_available():
            device = "cuda"
            name = torch.cuda.get_device_name(0)
            logger.info(
                "EmbeddingAdapter: using device=cuda (%s)", name,
                extra={"event": "embedding_device_selected", "device": device, "device_name": name},
            )
            return device

        if torch.backends.mps.is_available():
            device = "mps"
            logger.info(
                "EmbeddingAdapter: using device=mps (Apple Silicon)",
                extra={"event": "embedding_device_selected", "device": device},
            )
            return device

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            device = "xpu"
            logger.info(
                "EmbeddingAdapter: using device=xpu (Intel XPU)",
                extra={"event": "embedding_device_selected", "device": device},
            )
            return device

    except ImportError:
        logger.warning("PyTorch not available — EmbeddingAdapter will use cpu.")

    logger.info(
        "EmbeddingAdapter: using device=cpu (no GPU detected)",
        extra={"event": "embedding_device_selected", "device": "cpu"},
    )
    return "cpu"


_DEVICE: str = _resolve_device()

# ── Model registry (loaded from YAML at module import) ────────────────────────

_YAML_PATH = Path(__file__).parents[2] / "config" / "embedding_models.yaml"
_MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _load_registry() -> Dict[str, Dict[str, Any]]:
    """Parse embedding_models.yaml → {model_name: config_dict}."""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not available — embedding model registry will be empty.")
        return {}

    if not _YAML_PATH.exists():
        logger.warning("embedding_models.yaml not found at '%s'.", _YAML_PATH)
        return {}

    with open(_YAML_PATH, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    registry: Dict[str, Dict[str, Any]] = {}
    for m in data.get("models", []):
        registry[m["name"]] = m
    logger.debug("EmbeddingAdapter: registered %d models from YAML.", len(registry))
    return registry


_MODEL_REGISTRY = _load_registry()

# ── In-memory model cache (on-demand, per-worker-process) ─────────────────────

# {model_name: SentenceTransformer instance}
_model_cache: Dict[str, Any] = {}


def _get_model(model_name: str) -> Any:
    """
    Return the cached SentenceTransformer for model_name, loading it on
    demand from the HF disk cache if not already in memory.

    Raises:
        RuntimeError: If the model name is not in the registry or the load fails.
    """
    if model_name in _model_cache:
        return _model_cache[model_name]

    if model_name not in _MODEL_REGISTRY:
        raise RuntimeError(
            f"Model '{model_name}' is not in the embedding model registry. "
            "Add it to app/config/embedding_models.yaml first."
        )

    cache_dir = os.environ.get(
        "HF_HOME", "/workspace/.cache/huggingface"
    )
    logger.info(
        "EmbeddingAdapter: loading model '%s' onto device=%s from cache=%s",
        model_name, _DEVICE, cache_dir,
        extra={
            "event": "embedding_model_load_start",
            "model": model_name,
            "device": _DEVICE,
            "cache_dir": cache_dir,
        },
    )

    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            model_name,
            device=_DEVICE,
            cache_folder=cache_dir,
            trust_remote_code=True,  # required for Harrier (decoder-based)
        )
        _model_cache[model_name] = model
        logger.info(
            "EmbeddingAdapter: model '%s' loaded successfully.",
            model_name,
            extra={"event": "embedding_model_loaded", "model": model_name},
        )
        return model

    except Exception as exc:
        raise RuntimeError(
            f"Failed to load embedding model '{model_name}': {exc}"
        ) from exc


# ── Public API ────────────────────────────────────────────────────────────────

def get_model_config(model_name: str) -> Dict[str, Any]:
    """Return the YAML config dict for a model, or raise KeyError if unknown."""
    if model_name not in _MODEL_REGISTRY:
        raise KeyError(
            f"Model '{model_name}' not found in embedding_models.yaml registry."
        )
    return _MODEL_REGISTRY[model_name]


def get_supported_languages(model_name: str) -> List[str]:
    """
    Return the list of ISO 639-1 language codes supported by model_name.
    Returns ["*"] if the model supports all languages.
    """
    cfg = get_model_config(model_name)
    return cfg.get("languages", [])


def is_model_known(model_name: str) -> bool:
    """Return True if model_name is listed in the registry."""
    return model_name in _MODEL_REGISTRY


def embed_texts(
    texts: List[str],
    model_name: str,
    is_query: bool = False,
) -> List[List[float]]:
    """
    Embed a batch of texts using model_name and return float32 vectors.

    For models that require instruction prefixes (requires_prefix=true),
    the appropriate prefix is prepended automatically:
        - query texts  → prefix_query
        - passage texts (is_query=False) → prefix_passage (usually "")

    Args:
        texts:      List of text strings to embed.
        model_name: HuggingFace model repo name (must be in registry).
        is_query:   True for query embedding, False for passage/document embedding.

    Returns:
        List of float vectors, one per input text.
    """
    cfg = get_model_config(model_name)
    model = _get_model(model_name)

    # Apply instruction prefix if required by the model
    texts_to_encode = texts
    if cfg.get("requires_prefix", False):
        prefix = cfg.get("prefix_query" if is_query else "prefix_passage", "")
        if prefix:
            texts_to_encode = [f"{prefix}{t}" for t in texts]

    embeddings = model.encode(
        texts_to_encode,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return embeddings.tolist()


def unload_models(model_names: List[str]) -> None:
    """
    Explicitly unload the listed models from VRAM/RAM.

    Called by finalize_embedding_task after all vectors for a data connector
    are stored in Qdrant, to immediately free GPU memory.

    Steps:
        1. Delete model objects from the in-process cache.
        2. Call gc.collect() to trigger CPython reference-count cleanup.
        3. Clear the PyTorch device cache (CUDA / MPS).
    """
    removed = []
    for name in model_names:
        if name in _model_cache:
            del _model_cache[name]
            removed.append(name)

    if not removed:
        return

    gc.collect()

    try:
        import torch
        if _DEVICE == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info(
                "EmbeddingAdapter: CUDA cache cleared after unloading %s",
                removed,
                extra={"event": "embedding_model_unloaded", "models": removed, "device": "cuda"},
            )
        elif _DEVICE == "mps":
            try:
                torch.mps.empty_cache()
            except AttributeError:
                pass  # torch.mps.empty_cache added in PyTorch 2.0
            logger.info(
                "EmbeddingAdapter: MPS cache cleared after unloading %s",
                removed,
                extra={"event": "embedding_model_unloaded", "models": removed, "device": "mps"},
            )
        else:
            logger.info(
                "EmbeddingAdapter: models unloaded from CPU memory: %s",
                removed,
                extra={"event": "embedding_model_unloaded", "models": removed, "device": _DEVICE},
            )
    except ImportError:
        logger.debug("torch not available during unload — gc.collect() already called.")
