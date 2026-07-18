"""
app.tools.json_tool — Safe JSON inspection system tool.

Platform-authored, installed at build time, executed in-process.
Provides JSON key listing and nested value extraction without code execution.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from langchain_core.tools import BaseTool

from app.schemas.tool_schema import ToolDefinition


class SafeJsonInspectorTool(BaseTool):
    """LangChain tool wrapper for inspecting JSON structures safely."""

    name: str = "json_inspector"
    description: str = (
        "Inspect JSON objects — list keys at top level or extract values "
        "by dot-separated key path (e.g. 'data.user.name')."
    )

    def _run(self, action: str, data: Dict[str, Any], path: Optional[str] = None) -> str:
        if not isinstance(data, (dict, list)):
            try:
                data = json.loads(str(data))
            except Exception as exc:
                return f"Error: Data must be a valid JSON object or list. ({exc})"

        if action == "list_keys":
            if isinstance(data, dict):
                return json.dumps(list(data.keys()))
            elif isinstance(data, list):
                return f"JSON Array with {len(data)} items."
            return "Value is a scalar."

        elif action == "get_value":
            if not path:
                return json.dumps(data, indent=2)

            keys = path.split(".")
            curr = data
            for k in keys:
                if isinstance(curr, dict) and k in curr:
                    curr = curr[k]
                elif isinstance(curr, list) and k.isdigit() and int(k) < len(curr):
                    curr = curr[int(k)]
                else:
                    return f"Error: Key path '{path}' not found."

            return json.dumps(curr, indent=2) if isinstance(curr, (dict, list)) else str(curr)

        return f"Error: Unknown action '{action}'. Use 'list_keys' or 'get_value'."

    async def _arun(self, action: str, data: Dict[str, Any], path: Optional[str] = None) -> str:
        return self._run(action=action, data=data, path=path)


tool = ToolDefinition(
    name="json_tool",
    version="1.0.0",
    display_name="JSON Inspector",
    description=(
        "Inspect JSON data structures — list keys at a given path or "
        "extract values by path. Useful for exploring API responses, "
        "configuration files, or any JSON data."
    ),
    capabilities=["json_inspection", "data_exploration", "key_listing"],
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_keys", "get_value"],
                "description": "Whether to list keys or get a specific value.",
            },
            "path": {
                "type": "string",
                "description": "Dot-separated path into the JSON (e.g. 'data.users.0.name').",
            },
            "data": {
                "type": "object",
                "description": "The JSON object to inspect.",
            },
        },
        "required": ["action", "data"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Keys list or extracted value as string.",
            }
        },
    },
    usage_examples=[
        {
            "input": {
                "action": "list_keys",
                "data": {"name": "test", "version": "1.0", "config": {"key": "val"}},
            },
            "description": "List top-level keys of a JSON object",
        },
    ],
    langchain_tool=SafeJsonInspectorTool(),
    max_output_bytes=1_048_576,
    timeout_seconds=10,
)
