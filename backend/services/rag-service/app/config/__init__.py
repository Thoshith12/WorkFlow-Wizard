"""
app.config — RAG service configuration package.

Exports:
    LANGUAGE_MAP — ISO 639-1 code → full English language name dict,
                   loaded from embedding_models.yaml at import time.
"""
from app.config.language_map import LANGUAGE_MAP

__all__ = ["LANGUAGE_MAP"]
