"""
app.pipeline.preprocessing.steps — Preprocessing pipeline steps defined as separate functions.

The 5 individual steps:
  1. fix_encoding        — Strip control/null bytes and repair mojibake with ftfy
  2. normalize_unicode   — Normalize text to NFC standard form
  3. collapse_whitespace — Collapse multiple spaces, tabs, and newlines
  4. passes_quality      — Quality threshold filter (words, symbols, digits)
  5. detect_languages    — Identify languages using FastText model on random text windows
"""
import logging
import os
import random
import re
import unicodedata

import ftfy

logger = logging.getLogger(__name__)

# ── Pre-compiled regex patterns ───────────────────────────────────────────────
_MULTI_SPACE    = re.compile(r"[ ]{2,}")    # 2+ spaces   → 1 space
_MULTI_TAB      = re.compile(r"\t{2,}")     # 2+ tabs     → 1 tab
_MULTI_NL       = re.compile(r"\n{3,}")     # 3+ newlines → 2 newlines
_SYMBOL_PATTERN = re.compile(r"[^\w\s.,!?;:'\"\-\(\)\[\]{}/@#%&*+=<>|\\~`^]")
_CONTROL_CHARS  = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # strip PDF junk


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: Fix Encoding
# ═══════════════════════════════════════════════════════════════════════════════

def fix_encoding(text: str) -> str:
    """
    Repair misencoded text / mojibake and remove junk characters:
      - Strips null bytes (\x00) and control characters that crash C/C++ backends
      - Fixes misencoded UTF-8 sequences using ftfy
    """
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = _CONTROL_CHARS.sub(" ", text)
    return ftfy.fix_text(text)


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: Unicode Normalization
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_unicode(text: str) -> str:
    """
    Normalize text to Unicode Normalization Form C (NFC).
    Ensures characters composed of multiple codepoints are standardized.
    """
    if not text:
        return ""
    return unicodedata.normalize("NFC", text)


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3: Whitespace Collapsing
# ═══════════════════════════════════════════════════════════════════════════════

def collapse_whitespace(text: str) -> str:
    """
    Collapse runs of whitespace to prevent index bloat:
      - 2 or more consecutive spaces  → single space
      - 2 or more consecutive tabs    → single tab
      - 3 or more consecutive newlines → double newline (preserves paragraphs)
    """
    if not text:
        return ""
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_TAB.sub("\t", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Step 4: Quality Filtering
# ═══════════════════════════════════════════════════════════════════════════════

def passes_quality(
    text: str,
    min_words: int = 5,
    max_symbol_ratio: float = 0.4,
    max_digit_ratio: float = 0.6,
) -> bool:
    """
    Return True if the text passes all quality thresholds:
      - Word count >= min_words
      - Symbol ratio <= max_symbol_ratio
      - Digit ratio <= max_digit_ratio
    """
    if not text:
        return False
    words = text.split()
    if len(words) < min_words:
        return False
    total = len(text)
    if len(_SYMBOL_PATTERN.findall(text)) / total > max_symbol_ratio:
        return False
    if sum(ch.isdigit() for ch in text) / total > max_digit_ratio:
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Step 5: Language Detection (FastText model singleton)
# ═══════════════════════════════════════════════════════════════════════════════

_MODEL_PATH = os.environ.get("FASTTEXT_MODEL_PATH", "/workspace/lid.176.ftz")
_ft_model = None  # module-level singleton


def _load_model():
    """Load FastText model into memory once and reuse."""
    global _ft_model
    if _ft_model is not None:
        return _ft_model

    if not os.path.exists(_MODEL_PATH):
        raise RuntimeError(f"FastText model file not found at '{_MODEL_PATH}'")

    try:
        import fasttext
        fasttext.FastText.eprint = lambda x: None  # silence internal warnings
        _ft_model = fasttext.load_model(_MODEL_PATH)
        logger.info(
            "FastText language model loaded",
            extra={
                "event": "fasttext_model_loaded",
                "model_path": _MODEL_PATH,
                "model_size_mb": round(os.path.getsize(_MODEL_PATH) / 1_048_576, 1),
            },
        )
        return _ft_model
    except Exception as exc:
        raise RuntimeError(f"Failed to initialize fasttext model: {exc}") from exc


def _safe_sample(text: str) -> str:
    """Strip characters that crash FastText predict()."""
    text = text.replace("\x00", "")
    text = _CONTROL_CHARS.sub(" ", text)
    text = text.replace("\n", " ").replace("\r", " ")
    text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    return text.strip()


def detect_languages(pages: list, n_samples: int = 3, sample_len: int = 150) -> list:
    """
    Detect unique languages per page, returning a unique sorted list for the document.

    Strategy:
      For each page in pages:
        1. Draw up to `n_samples` random windows of `sample_len` characters.
        2. Clean and classify each window with FastText to get the top language.
        3. Append detected unique languages to the document-wide list.
    """
    if not pages:
        logger.warning(
            "Language detection skipped — no pages",
            extra={"event": "lang_detection_skipped", "reason": "no_pages"},
        )
        return []

    try:
        model = _load_model()
    except RuntimeError as exc:
        logger.warning(
            "Language detection skipped — FastText model unavailable",
            extra={"event": "lang_detection_skipped", "reason": "model_unavailable", "error": str(exc)},
        )
        return []

    detected = set()
    total_samples = 0

    for page_idx, page in enumerate(pages):
        page_num = page.get("page_number", page_idx + 1)
        content = page.get("content", "").strip()
        if not content:
            continue

        # Build samples for this page
        if len(content) <= sample_len:
            samples = [content]
        else:
            max_start = len(content) - sample_len
            starts = random.sample(range(max_start + 1), k=min(n_samples, max_start + 1))
            samples = []
            for s in starts:
                end = min(s + sample_len, len(content))
                while end < len(content) and not content[end].isspace():
                    end += 1
                samples.append(content[s:end].strip())

        # Predict language for each sample of this page
        for sample in samples:
            cleaned_sample = _safe_sample(sample)
            if not cleaned_sample:
                continue
            try:
                labels, confidences = model.predict(cleaned_sample, k=1)
                if labels:
                    lang_code = labels[0].replace("__label__", "")
                    detected.add(lang_code)
                    total_samples += 1
                    logger.debug(
                        "FastText page sample classified",
                        extra={
                            "event": "fasttext_sample_done",
                            "page_number": page_num,
                            "lang": lang_code,
                            "confidence": round(float(confidences[0]), 4),
                            "sample_len": len(cleaned_sample),
                        },
                    )
            except Exception as exc:
                logger.warning(
                    "FastText predict failed for sample",
                    extra={
                        "event": "fasttext_predict_failed",
                        "page_number": page_num,
                        "error": str(exc),
                        "sample_preview": cleaned_sample[:80],
                    },
                )

    result = sorted(detected)
    logger.info(
        "Language detection completed across pages",
        extra={
            "event": "lang_detection_done",
            "languages": result,
            "samples_used": total_samples,
            "page_count": len(pages),
        },
    )
    return result
