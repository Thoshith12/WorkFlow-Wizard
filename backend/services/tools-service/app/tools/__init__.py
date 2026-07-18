"""
app.tools — Pre-defined system tool registry.

Each module in this package exports a `tool` variable of type ToolDefinition.
This __init__.py collects them all into the SYSTEM_TOOLS dict, keyed by
"{name}@{version}" for O(1) lookup.

System tools are:
  - Platform-authored, committed to repo, reviewed in PRs.
  - Installed at Docker image build time.
  - Executed in-process via ainvoke() — no sandbox.
  - TRUSTED by definition.
"""
from __future__ import annotations

import logging
from typing import Dict

from app.schemas.tool_schema import ToolDefinition

logger = logging.getLogger(__name__)

# ── Import each tool module ──────────────────────────────────────────────────
from app.tools import (
    web_search,
    wikipedia,
    arxiv,
    http_request,
    json_tool,
    python_repl,
)

# ── Build the registry ───────────────────────────────────────────────────────
_TOOL_MODULES = [web_search, wikipedia, arxiv, http_request, json_tool, python_repl]

SYSTEM_TOOLS: Dict[str, ToolDefinition] = {}

for _mod in _TOOL_MODULES:
    _def: ToolDefinition = _mod.tool
    _key = f"{_def.name}@{_def.version}"
    if _key in SYSTEM_TOOLS:
        raise RuntimeError(f"Duplicate system tool key: {_key}")
    SYSTEM_TOOLS[_key] = _def
    logger.info("Registered system tool: %s", _key)

# Also build a name-only set for collision checks against custom tools.
SYSTEM_TOOL_NAMES: frozenset[str] = frozenset(d.name for d in SYSTEM_TOOLS.values())

logger.info("Loaded %d system tools: %s", len(SYSTEM_TOOLS), list(SYSTEM_TOOLS.keys()))
