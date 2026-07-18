"""
app.schemas.custom_tool — Pydantic schemas for custom tool CRUD operations.

Includes import validation (blocked imports gate) at the schema layer.
Config keys are returned in detail but values are redacted to prevent
secret leakage through the API.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# ── Blocked imports — never allowed in custom tool code ──────────────────────
# These could be used to escape the sandbox or access host resources.
BLOCKED_IMPORTS = frozenset({
    "os", "sys", "subprocess", "shutil", "ctypes",
    "importlib", "pathlib", "signal", "socket", "multiprocessing",
    "threading", "asyncio.subprocess", "pty", "resource",
    "builtins", "__builtins__",
})

# Pattern to detect blocked import statements in code strings.
_IMPORT_PATTERN = re.compile(
    r"^\s*(?:import|from)\s+([\w.]+)",
    re.MULTILINE,
)


def _validate_code_imports(code: Optional[str], field_name: str) -> Optional[str]:
    """Scan code for blocked import statements."""
    if code is None:
        return code
    for match in _IMPORT_PATTERN.finditer(code):
        module_root = match.group(1).split(".")[0]
        if module_root in BLOCKED_IMPORTS:
            raise ValueError(
                f"Blocked import '{match.group(1)}' found in {field_name}. "
                f"Module '{module_root}' is not permitted in custom tool code."
            )
    return code


# ── Create Schema ─────────────────────────────────────────────────────────────


class CustomToolCreate(BaseModel):
    """Request body for POST /api/tools/custom."""

    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-z0-9_-]+$")
    version: str = Field(..., min_length=1, max_length=50, pattern=r"^\d+\.\d+\.\d+$")
    display_name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)

    preprocessing_code: Optional[str] = None
    processing_code: str = Field(..., min_length=1)
    postprocessing_code: Optional[str] = None

    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Optional[Dict[str, Any]] = None
    usage_examples: List[Dict[str, Any]] = Field(default_factory=list)

    imports: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list, max_length=20)
    config: Dict[str, Any] = Field(default_factory=dict)

    tags: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)

    @field_validator("imports")
    @classmethod
    def validate_imports(cls, v: List[str]) -> List[str]:
        for imp in v:
            root = imp.split(".")[0]
            if root in BLOCKED_IMPORTS:
                raise ValueError(f"Import '{imp}' is blocked — module '{root}' is not permitted.")
        return v

    @field_validator("preprocessing_code")
    @classmethod
    def validate_preprocessing(cls, v: Optional[str]) -> Optional[str]:
        return _validate_code_imports(v, "preprocessing_code")

    @field_validator("processing_code")
    @classmethod
    def validate_processing(cls, v: str) -> str:
        _validate_code_imports(v, "processing_code")
        if "async def process" not in v:
            raise ValueError(
                "processing_code must define 'async def process(input_data)' as the entry point."
            )
        return v

    @field_validator("postprocessing_code")
    @classmethod
    def validate_postprocessing(cls, v: Optional[str]) -> Optional[str]:
        return _validate_code_imports(v, "postprocessing_code")

    @field_validator("requirements")
    @classmethod
    def validate_requirements(cls, v: List[str]) -> List[str]:
        if len(v) > 20:
            raise ValueError("Maximum 20 pip requirements per tool.")
        return v


# ── Update Schema ─────────────────────────────────────────────────────────────


class CustomToolUpdate(BaseModel):
    """
    Request body for PATCH /api/tools/custom/{name}/{version}.

    All fields are optional — only provided fields are updated.
    name and version are immutable and must NOT be sent.
    """

    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, min_length=1)

    preprocessing_code: Optional[str] = None
    processing_code: Optional[str] = None
    postprocessing_code: Optional[str] = None

    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    usage_examples: Optional[List[Dict[str, Any]]] = None

    imports: Optional[List[str]] = None
    requirements: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None

    tags: Optional[List[str]] = None
    capabilities: Optional[List[str]] = None
    status: Optional[str] = None

    @field_validator("imports")
    @classmethod
    def validate_imports(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        for imp in v:
            root = imp.split(".")[0]
            if root in BLOCKED_IMPORTS:
                raise ValueError(f"Import '{imp}' is blocked — module '{root}' is not permitted.")
        return v

    @field_validator("preprocessing_code")
    @classmethod
    def validate_preprocessing(cls, v: Optional[str]) -> Optional[str]:
        return _validate_code_imports(v, "preprocessing_code")

    @field_validator("processing_code")
    @classmethod
    def validate_processing(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            _validate_code_imports(v, "processing_code")
            if "async def process" not in v:
                raise ValueError(
                    "processing_code must define 'async def process(input_data)' as the entry point."
                )
        return v

    @field_validator("postprocessing_code")
    @classmethod
    def validate_postprocessing(cls, v: Optional[str]) -> Optional[str]:
        return _validate_code_imports(v, "postprocessing_code")

    @field_validator("requirements")
    @classmethod
    def validate_requirements(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None and len(v) > 20:
            raise ValueError("Maximum 20 pip requirements per tool.")
        return v


# ── Detail Response Schema ────────────────────────────────────────────────────


class CustomToolDetail(BaseModel):
    """
    Response body for GET /api/tools/custom/{name}/{version}.

    Returns the full tool definition including code, imports, requirements,
    and config KEYS (but NOT values — to prevent secret leakage).
    """

    id: str
    name: str
    version: str
    display_name: str
    description: str
    owner_id: str

    preprocessing_code: Optional[str] = None
    processing_code: str
    postprocessing_code: Optional[str] = None

    input_schema: Dict[str, Any] = {}
    output_schema: Optional[Dict[str, Any]] = None
    usage_examples: List[Dict[str, Any]] = []

    imports: List[str] = []
    requirements: List[str] = []
    config_keys: List[str] = []  # config keys only — values redacted

    tags: List[str] = []
    capabilities: List[str] = []
    status: str = "active"

    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
