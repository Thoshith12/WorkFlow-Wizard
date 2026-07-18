"""
app.config.language_map — ISO 639-1 language code mapping.

Loads the language_map section from embedding_models.yaml at module import
time and exposes it as a plain Python dict. This keeps a single source of
truth: the YAML file owns all ISO code ↔ human-readable name definitions.

FastText lid.176 returns two-letter ISO 639-1 codes (e.g. "hi", "ta").
All HuggingFace model language lists in embedding_models.yaml use the
same codes, so no translation is ever required between the two systems.

Usage:
    from app.config.language_map import LANGUAGE_MAP
    print(LANGUAGE_MAP.get("ta", "ta"))   # → "Tamil"
    print(LANGUAGE_MAP.get("xx", "xx"))   # → "xx"  (safe fallback)
"""
import logging
import os
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

# Resolve path relative to this file so it works from any working directory
_YAML_PATH = Path(__file__).parent / "embedding_models.yaml"


def _load_language_map() -> Dict[str, str]:
    """Parse the language_map section from embedding_models.yaml."""
    try:
        import yaml  # PyYAML — listed in requirements.txt
    except ImportError as exc:
        logger.warning(
            "PyYAML not installed — LANGUAGE_MAP will be empty: %s", exc
        )
        return {}

    if not _YAML_PATH.exists():
        logger.warning(
            "embedding_models.yaml not found at '%s' — LANGUAGE_MAP will be empty.",
            _YAML_PATH,
        )
        return {}

    with open(_YAML_PATH, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    lang_map: Dict[str, str] = data.get("language_map", {})
    logger.debug(
        "Language map loaded: %d ISO codes from '%s'",
        len(lang_map),
        _YAML_PATH,
    )
    return lang_map


# Module-level singleton — loaded once at import time.
LANGUAGE_MAP: Dict[str, str] = _load_language_map()
