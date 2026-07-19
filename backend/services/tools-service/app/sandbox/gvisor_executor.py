"""
app.sandbox.gvisor_executor — gVisor sandbox executor with two-level backpressure.

Implements the production sandbox execution path:
  1. Acquire global semaphore slot (or raise SandboxBusy + 503)
  2. Acquire per-tool semaphore slot
  3. Get or boot a warm container for this tool via SandboxPool
  4. Send execution request over loopback TCP to the in-container server
  5. Wait for result (non-blocking via add_reader, not poll loop)
  6. Release semaphore slots

Timeout semantics:
  - EXEC_TIMEOUT kills the subprocess ONLY. Container stays warm.
  - SANDBOX_QUEUE_TIMEOUT is the patience waiting for a semaphore slot.
  - Idle timeout (5 min) is the only container lifecycle driver.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Dict

from app.config.tool_settings import tool_settings
from app.models.custom_tool import CustomTool
from app.sandbox.base_executor import (
    BaseSandboxExecutor,
    SandboxBusy,
    SandboxError,
    SandboxTimeout,
)

logger = logging.getLogger(__name__)


class GVisorSandboxExecutor(BaseSandboxExecutor):
    """
    Production sandbox executor using gVisor warm containers.

    Two-level backpressure:
      - Global semaphore: bounds total concurrent executions across ALL tools.
      - Per-tool semaphore: bounds concurrent executions for a single tool.
    """

    def __init__(self) -> None:
        cfg = tool_settings.sandbox
        self._global_sem = asyncio.Semaphore(cfg.max_concurrent_global)
        self._per_tool_sems: Dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(cfg.max_concurrent_per_tool)
        )
        self._queue_timeout = cfg.queue_timeout_seconds
        self._exec_timeout = cfg.exec_timeout_seconds
        self._max_output_bytes = cfg.max_output_bytes

    async def execute(
        self,
        *,
        tool: CustomTool,
        input_data: Dict[str, Any],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """Execute user code in a gVisor warm container."""
        tool_key = f"{tool.name}@{tool.version}"
        per_tool_sem = self._per_tool_sems[tool_key]

        # ── Level 1: Global semaphore ─────────────────────────────────────
        try:
            await asyncio.wait_for(
                self._global_sem.acquire(),
                timeout=self._queue_timeout,
            )
        except asyncio.TimeoutError:
            raise SandboxBusy(
                f"Global sandbox queue full — {tool_settings.sandbox.max_concurrent_global} "
                "concurrent executions reached. Retry after a few seconds."
            )

        try:
            # ── Level 2: Per-tool semaphore ───────────────────────────────
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
        bundle_path = await sandbox_pool.get_or_start(tool)
        sock_path = f"{bundle_path}/run/sandbox/tool.sock"

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
                asyncio.open_unix_connection(sock_path),
                timeout=5.0,
            )
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as exc:
            # Dead socket — invalidate and retry once
            logger.warning("Sandbox connect failed for %s, invalidating: %s", tool_key, exc)
            await sandbox_pool.invalidate(tool.name, tool.version)
            bundle_path = await sandbox_pool.get_or_start(tool)
            sock_path = f"{bundle_path}/run/sandbox/tool.sock"
            reader, writer = await asyncio.open_unix_connection(sock_path)

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
            raise SandboxError(f"Container closed connection unexpectedly for '{tool_key}'.")
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
        logger.info("GVisorSandboxExecutor shut down.")


# Module-level singleton
gvisor_executor = GVisorSandboxExecutor()
