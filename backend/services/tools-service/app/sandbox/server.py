"""
app.sandbox.server — Sandboxed execution server running inside gVisor container.

Reads execution request payloads from sys.stdin.buffer, executes user code in an
isolated namespace, and writes length-prefixed JSON responses to sys.stdout.buffer.

Resource limits (memory, pids, cpu) are enforced via POSIX setrlimit so they
work regardless of whether gVisor is running with --ignore-cgroups (rootless).
The limits are injected via /run/sandbox/config.json by oci.py at bundle build
time, keyed under '_sandbox_limits'.
"""
from __future__ import annotations

import asyncio
import builtins
import importlib
import json
import logging
import os
import resource
import struct
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("sandbox.server")

CONFIG_PATH = Path("/run/sandbox/config.json")


def _apply_resource_limits(limits: Dict[str, Any]) -> None:
    """
    Apply POSIX resource limits from the config injected by oci.py.

    These work regardless of --ignore-cgroups because they are enforced by the
    Linux kernel's per-process rlimit subsystem, not cgroups:

      RLIMIT_AS   — virtual address space cap = effective RAM cap.
                    malloc/bytearray raises MemoryError when exceeded.
      RLIMIT_NPROC — max number of processes/threads the sandbox can spawn.
      RLIMIT_CPU  — max CPU seconds (soft=hard for hard enforcement).
    """
    memory_bytes = limits.get("memory_bytes")
    if memory_bytes and memory_bytes > 0:
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            logger.info("RLIMIT_AS set to %d bytes (%.1f MB)", memory_bytes, memory_bytes / (1024 ** 2))
        except (ValueError, resource.error) as exc:
            logger.warning("Failed to set RLIMIT_AS: %s", exc)

    pids_limit = limits.get("pids_limit")
    if pids_limit and pids_limit > 0:
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (pids_limit, pids_limit))
            logger.info("RLIMIT_NPROC set to %d", pids_limit)
        except (ValueError, resource.error) as exc:
            logger.warning("Failed to set RLIMIT_NPROC: %s", exc)

    cpu_seconds = limits.get("cpu_seconds")
    if cpu_seconds and cpu_seconds > 0:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            logger.info("RLIMIT_CPU set to %d seconds", cpu_seconds)
        except (ValueError, resource.error) as exc:
            logger.warning("Failed to set RLIMIT_CPU: %s", exc)


async def _execute_user_code(
    *,
    preprocessing_code: Optional[str],
    processing_code: str,
    postprocessing_code: Optional[str],
    imports: list,
    input_data: dict,
    timeout: float,
) -> Dict[str, Any]:
    """Execute user code directly in a clean dictionary namespace."""
    try:
        config = {}
        if CONFIG_PATH.exists():
            try:
                with open(str(CONFIG_PATH)) as f:
                    config = json.load(f)
            except Exception:
                pass

        ns: Dict[str, Any] = {
            "__builtins__": builtins,
            "config": config,
            "input_data": input_data,
        }

        ns["os"] = os
        ns["json"] = json
        ns["math"] = importlib.import_module("math")
        ns["re"] = importlib.import_module("re")
        ns["datetime"] = importlib.import_module("datetime")
        ns["collections"] = importlib.import_module("collections")

        for module_name in imports:
            try:
                ns[module_name.split(".")[-1]] = importlib.import_module(module_name)
            except ImportError as exc:
                return {"status": "error", "error": f"Import failed: {exc}"}

        if preprocessing_code:
            exec(preprocessing_code, ns)

        exec(processing_code, ns)

        if "process" not in ns or not callable(ns["process"]):
            return {
                "status": "error",
                "error": "processing_code must define 'async def process(input_data)'",
            }

        coro = ns["process"](input_data)
        if asyncio.iscoroutine(coro):
            res = await coro
        else:
            res = coro

        ns["res"] = res

        if postprocessing_code:
            exec(postprocessing_code, ns)
            res = ns.get("res", res)

        return {"status": "ok", "result": res}

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("User code execution exception: %s\n%s", exc, tb)
        error_msg = f"{type(exc).__name__}: {str(exc)[:500]}"
        return {"status": "error", "error": error_msg}


async def main() -> None:
    """Read length-prefixed JSON requests from stdin, write responses to stdout."""
    # Apply POSIX resource limits before any user code runs.
    # Limits are injected by oci.py into /run/sandbox/config.json under
    # the '_sandbox_limits' key and enforced via setrlimit — works
    # regardless of --ignore-cgroups on rootless gVisor.
    config = {}
    if CONFIG_PATH.exists():
        try:
            with open(str(CONFIG_PATH)) as f:
                config = json.load(f)
        except Exception as exc:
            logger.warning("Failed to load config.json: %s", exc)

    sandbox_limits = config.get("_sandbox_limits", {})
    if sandbox_limits:
        _apply_resource_limits(sandbox_limits)
    else:
        logger.warning("No '_sandbox_limits' in config.json — resource limits NOT enforced.")

    logger.info("Sandbox server active on stdio pipe.")
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    while True:
        try:
            raw_len = await reader.readexactly(4)
        except (asyncio.IncompleteReadError, EOFError):
            break

        msg_len = struct.unpack(">I", raw_len)[0]
        if msg_len == 0:
            break
        raw_msg = await reader.readexactly(msg_len)
        request = json.loads(raw_msg)

        timeout = float(request.get("timeout_seconds", 30))
        result = await _execute_user_code(
            preprocessing_code=request.get("preprocessing_code"),
            processing_code=request["processing_code"],
            postprocessing_code=request.get("postprocessing_code"),
            imports=request.get("imports", []),
            input_data=request.get("input_data", {}),
            timeout=timeout,
        )

        response_bytes = json.dumps(result, default=str).encode()
        sys.stdout.buffer.write(struct.pack(">I", len(response_bytes)))
        sys.stdout.buffer.write(response_bytes)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    asyncio.run(main())
