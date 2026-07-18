"""
app.tools.python_repl — Python REPL system tool.

Platform-authored, installed at build time, executed in-process.

TRUST MODEL: Platform-authored static wrapper — NOT a surface for
user-submitted code. Executes code generated internally by platform agents.
User-submitted code uses custom tools (sandboxed via gVisor).
"""
from __future__ import annotations

import io
import sys
from typing import Any, Dict
from langchain_core.tools import BaseTool

from app.schemas.tool_schema import ToolDefinition


class SafePythonREPLTool(BaseTool):
    """In-process REPL tool capturing stdout."""

    name: str = "python_repl"
    description: str = "Execute Python code and return stdout."

    def _run(self, query: str) -> str:
        old_stdout = sys.stdout
        buf = io.StringIO()
        sys.stdout = buf
        try:
            glob: Dict[str, Any] = {}
            exec(query, glob)
            output = buf.getvalue()
            return output if output else "Execution successful (no output)."
        except Exception as exc:
            return f"Execution error: {exc}"
        finally:
            sys.stdout = old_stdout

    async def _arun(self, query: str) -> str:
        return self._run(query)


tool = ToolDefinition(
    name="python_repl",
    version="1.0.0",
    display_name="Python REPL",
    description=(
        "Execute Python code and return the output. Useful for calculations, "
        "data processing, and code verification. This tool is for agent-internal "
        "code execution only — user-submitted code uses custom tools (sandboxed)."
    ),
    capabilities=["code_execution", "calculation", "data_processing"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Python code to execute.",
            }
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Standard output from the executed Python code.",
            }
        },
    },
    usage_examples=[
        {
            "input": {"query": "print(sum(range(1, 101)))"},
            "description": "Calculate the sum of numbers 1 to 100",
        },
        {
            "input": {"query": "import math\nprint(math.factorial(20))"},
            "description": "Compute 20 factorial",
        },
    ],
    langchain_tool=SafePythonREPLTool(),
    max_output_bytes=1_048_576,
    timeout_seconds=30,
)
