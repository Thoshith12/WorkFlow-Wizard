"""
app.services.execution_engine — Tool execution routing.

Routes execution requests to the correct handler:
  - System tools → ainvoke() + asyncio.wait_for (in-process, non-blocking)
  - Custom tools → gVisor sandbox executor (out-of-process, isolated)

CRITICAL: System tools use ainvoke(), NEVER invoke().
Most LangChain community tools wrap synchronous requests calls.
invoke() would block the entire FastAPI event loop.
ainvoke() automatically offloads sync _run() to a thread pool.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.tool_settings import tool_settings
from app.models.custom_tool import CustomTool
from app.models.enums.tools import ToolType, ExecutionStatus
from app.repositories import execution_log as log_repo
from app.schemas.tool_schema import ToolDefinition
from app.services.registry import tool_registry

logger = logging.getLogger(__name__)


class ToolExecutionTimeout(Exception):
    """Raised when a tool execution exceeds its timeout."""
    pass


class ToolOutputTooLarge(Exception):
    """Raised when tool output exceeds the configured max_output_bytes."""
    pass


class ToolNotFound(Exception):
    """Raised when a requested tool is not in the registry."""
    pass


class ExecutionEngine:
    """Routes tool execution to the correct handler based on tool type."""

    async def execute(
        self,
        db: AsyncSession,
        *,
        tool_name: str,
        tool_version: str,
        input_data: Dict[str, Any],
        executed_by: str,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a tool and log the result.

        Returns a dict with: execution_id, tool_name, tool_version,
        tool_type, status, output, error, duration_ms.
        """
        tool = tool_registry.get(tool_name, tool_version)
        if tool is None:
            raise ToolNotFound(f"Tool '{tool_name}@{tool_version}' not found.")

        tool_type = tool_registry.get_tool_type(tool_name, tool_version)
        start = time.monotonic()
        status = ExecutionStatus.SUCCESS
        output = None
        error_msg = None

        try:
            if tool_type == ToolType.SYSTEM:
                assert isinstance(tool, ToolDefinition)
                effective_timeout = timeout_seconds or tool.timeout_seconds
                output = await self._run_system_tool(tool, input_data, effective_timeout)
            elif tool_type == ToolType.CUSTOM:
                assert isinstance(tool, CustomTool)
                effective_timeout = timeout_seconds or tool_settings.sandbox.exec_timeout_seconds
                output = await self._run_custom_tool(tool, input_data, effective_timeout)
            else:
                raise ToolNotFound(f"Unknown tool type for '{tool_name}@{tool_version}'.")

        except ToolExecutionTimeout as exc:
            status = ExecutionStatus.TIMEOUT
            error_msg = str(exc)
        except ToolOutputTooLarge as exc:
            status = ExecutionStatus.ERROR
            error_msg = str(exc)
        except Exception as exc:
            status = ExecutionStatus.ERROR
            # Truncate error to prevent config/secret leakage via stack traces.
            error_msg = f"{type(exc).__name__}: {str(exc)[:500]}"
            logger.error(
                "Tool execution failed: %s@%s — %s",
                tool_name, tool_version, error_msg,
            )

        duration_ms = (time.monotonic() - start) * 1000

        # Persist execution log
        log_entry = await log_repo.create_execution_log(
            db,
            tool_name=tool_name,
            tool_version=tool_version,
            tool_type=tool_type.value if tool_type else "unknown",
            executed_by=executed_by,
            input_payload=input_data,
            output_payload=output if status == ExecutionStatus.SUCCESS else None,
            status=status.value,
            error_message=error_msg,
            duration_ms=duration_ms,
        )

        return {
            "execution_id": str(log_entry.id),
            "tool_name": tool_name,
            "tool_version": tool_version,
            "tool_type": tool_type.value if tool_type else "unknown",
            "status": status.value,
            "output": output if status == ExecutionStatus.SUCCESS else None,
            "error": error_msg,
            "duration_ms": round(duration_ms, 2),
        }

    async def _run_system_tool(
        self,
        tool_def: ToolDefinition,
        input_data: Dict[str, Any],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """
        Run a LangChain system tool without blocking the event loop.

        Uses ainvoke() which automatically offloads sync _run() to a
        thread pool via run_in_executor. Wrapped in asyncio.wait_for()
        for timeout enforcement.

        NEVER call tool_def.langchain_tool.invoke() in an async path.
        """
        try:
            result = await asyncio.wait_for(
                tool_def.langchain_tool.ainvoke(input_data),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise ToolExecutionTimeout(
                f"System tool '{tool_def.name}' timed out after {timeout_seconds}s."
            )

        # Enforce output size cap
        raw = json.dumps(result, default=str).encode()
        if len(raw) > tool_def.max_output_bytes:
            raise ToolOutputTooLarge(
                f"Output exceeds {tool_def.max_output_bytes} bytes "
                f"(actual: {len(raw)} bytes)."
            )

        # Normalize output to dict
        if isinstance(result, str):
            return {"result": result}
        if isinstance(result, dict):
            return result
        return {"result": str(result)}

    async def _run_custom_tool(
        self,
        tool: CustomTool,
        input_data: Dict[str, Any],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """
        Run a custom tool inside the gVisor sandbox.

        Delegates to the sandbox executor which sends the request to
        the warm container's Unix socket server.
        """
        from app.sandbox.gvisor_executor import gvisor_executor

        result = await gvisor_executor.execute(
            tool=tool,
            input_data=input_data,
            timeout_seconds=timeout_seconds,
        )
        return result


# Module-level singleton
execution_engine = ExecutionEngine()
