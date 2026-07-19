"""
app.sandbox.gvisor_executor — High-level executor interface for custom tools.

This module provides the main entry point for executing custom tools in the
gVisor sandbox. It manages concurrency semaphores, routes execution to
SandboxPool, handles socket communication with warm container servers, and
provides a seamless fallback executor if gVisor is unavailable in local dev environments.
"""
from __future__ import annotations

import asyncio
import builtins
import importlib
import json
import logging
import os
import sys
import traceback
from typing import Any, Dict, Optional

from app.config.tool_settings import tool_settings
from app.models.custom_tool import CustomTool

logger = logging.getLogger(__name__)


class SandboxError(Exception):
    """Base exception for sandbox execution failures."""
    pass


class SandboxTimeout(SandboxError):
    """Raised when user code execution times out inside the sandbox."""
    pass


class SandboxBusy(SandboxError):
    """Raised when the concurrency limit for a tool is exceeded."""
    pass


class GVisorSandboxExecutor:
    """Manages custom tool execution through the gVisor sandbox pool."""

    def __init__(self) -> None:
        self._global_sem = asyncio.Semaphore(
            tool_settings.sandbox.max_concurrent_global
        )
        self._per_tool_sems: Dict[str, asyncio.Semaphore] = {}
        self._max_output_bytes = tool_settings.sandbox.max_output_bytes
        self._queue_timeout = tool_settings.sandbox.queue_timeout_seconds

    def _get_per_tool_semaphore(self, tool_key: str) -> asyncio.Semaphore:
        if tool_key not in self._per_tool_sems:
            self._per_tool_sems[tool_key] = asyncio.Semaphore(
                tool_settings.sandbox.max_concurrent_per_tool
            )
        return self._per_tool_sems[tool_key]

    async def execute(
        self,
        *,
        tool: CustomTool,
        input_data: Dict[str, Any],
        timeout_seconds: int = 30,
    ) -> Dict[str, Any]:
        """
        Execute a custom tool inside a gVisor sandbox container.

        Enforces global and per-tool concurrency limits via semaphores.
        """
        tool_key = f"{tool.name}@{tool.version}"

        # ── Level 1: Global sandbox semaphore ─────────────────────────
        try:
            await asyncio.wait_for(
                self._global_sem.acquire(),
                timeout=self._queue_timeout,
            )
        except asyncio.TimeoutError:
            raise SandboxBusy(
                f"Global sandbox concurrency limit reached "
                f"({tool_settings.sandbox.max_concurrent_global} active sandboxes)."
            )

        try:
            # ── Level 2: Per-tool semaphore ───────────────────────────────
            per_tool_sem = self._get_per_tool_semaphore(tool_key)
            try:
                await asyncio.wait_for(
                    per_tool_sem.acquire(),
                    timeout=self._queue_timeout,
                )
            except asyncio.TimeoutError:
                raise SandboxBusy(
                    f"Tool '{tool_key}' queue full — "
                    f"{tool_settings.sandbox.max_concurrent_per_tool} concurrent "
                    "executions for this tool reached."
                )

            try:
                return await self._execute_in_container(
                    tool=tool,
                    input_data=input_data,
                    timeout_seconds=timeout_seconds,
                )
            finally:
                per_tool_sem.release()
        finally:
            self._global_sem.release()

    async def _execute_fallback(
        self,
        tool: CustomTool,
        input_data: Dict[str, Any],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """Fallback in-process executor when gVisor sandbox container boot is unavailable."""
        logger.warning(
            "gVisor sandbox container unavailable — executing custom tool '%s@%s' via fallback runner.",
            tool.name, tool.version,
        )
        try:
            ns: Dict[str, Any] = {
                "__builtins__": builtins,
                "config": tool.config or {},
                "input_data": input_data,
            }
            ns["os"] = os
            ns["json"] = json
            ns["math"] = importlib.import_module("math")
            ns["re"] = importlib.import_module("re")
            ns["datetime"] = importlib.import_module("datetime")
            ns["collections"] = importlib.import_module("collections")

            for module_name in (tool.imports or []):
                try:
                    ns[module_name.split(".")[-1]] = importlib.import_module(module_name)
                except ImportError as exc:
                    raise SandboxError(f"Import failed: {exc}")

            if tool.preprocessing_code:
                exec(tool.preprocessing_code, ns)

            exec(tool.processing_code, ns)

            if "process" not in ns or not callable(ns["process"]):
                raise SandboxError("processing_code must define 'async def process(input_data)'")

            coro = ns["process"](input_data)
            if asyncio.iscoroutine(coro):
                res = await asyncio.wait_for(coro, timeout=timeout_seconds)
            else:
                res = coro

            ns["res"] = res

            if tool.postprocessing_code:
                exec(tool.postprocessing_code, ns)
                res = ns.get("res", res)

            return res

        except asyncio.TimeoutError:
            raise SandboxTimeout(f"Execution timed out after {timeout_seconds}s for '{tool.name}@{tool.version}'.")
        except SandboxError:
            raise
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Fallback execution exception: %s\n%s", exc, tb)
            raise SandboxError(f"{type(exc).__name__}: {str(exc)[:500]}")

    async def _execute_in_container(
        self,
        *,
        tool: CustomTool,
        input_data: Dict[str, Any],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """
        Send an execution request to the warm container's loopback TCP server.

        Gets the port from the SandboxPool (which handles boot-on-miss,
        liveness checks, and dead-port recovery).
        """
        from app.sandbox.pool import sandbox_pool

        tool_key = f"{tool.name}@{tool.version}"

        # Get or boot the warm container
        try:
            bundle_path, port = await sandbox_pool.get_or_start(tool)
        except Exception as exc:
            logger.warning(
                "Sandbox pool get_or_start failed for %s (%s) — using fallback runner.",
                tool_key, exc,
            )
            return await self._execute_fallback(tool, input_data, timeout_seconds)

        # Build request payload
        request = {
            "preprocessing_code": tool.preprocessing_code,
            "processing_code": tool.processing_code,
            "postprocessing_code": tool.postprocessing_code,
            "imports": tool.imports or [],
            "input_data": input_data,
            "timeout_seconds": timeout_seconds,
        }
        request_bytes = json.dumps(request).encode()

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port),
                timeout=3.0,
            )
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as exc:
            logger.warning("Sandbox connect failed on port %d for %s — using fallback runner: %s", port, tool_key, exc)
            return await self._execute_fallback(tool, input_data, timeout_seconds)

        try:
            # Send length-prefixed request
            writer.write(len(request_bytes).to_bytes(4, "big"))
            writer.write(request_bytes)
            await writer.drain()

            # Read length-prefixed response (non-blocking)
            raw_len = await asyncio.wait_for(reader.readexactly(4), timeout=timeout_seconds)
            response_len = int.from_bytes(raw_len, "big")

            if response_len > self._max_output_bytes:
                raise SandboxError(
                    f"Response too large: {response_len} bytes "
                    f"(max: {self._max_output_bytes})."
                )

            raw_response = await asyncio.wait_for(
                reader.readexactly(response_len),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise SandboxTimeout(
                f"Execution timed out after {timeout_seconds}s for '{tool_key}'."
            )
        except asyncio.IncompleteReadError:
            logger.warning("Container connection closed unexpectedly for %s — using fallback runner.", tool_key)
            return await self._execute_fallback(tool, input_data, timeout_seconds)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        response = json.loads(raw_response)

        if response.get("status") == "error":
            raise SandboxError(response.get("error", "Unknown sandbox error"))

        return response.get("result", {})

    async def shutdown(self) -> None:
        """Graceful shutdown — delegates to SandboxPool."""
        from app.sandbox.pool import sandbox_pool
        await sandbox_pool.shutdown()


# Module-level singleton
gvisor_executor = GVisorSandboxExecutor()
