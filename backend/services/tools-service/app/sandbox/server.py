"""
app.sandbox.server — Sandboxed execution server running inside gVisor container.

Reads execution request payloads from sys.stdin.buffer, executes user code in an
isolated namespace, and writes length-prefixed JSON responses to sys.stdout.buffer.

Resource limits:
  - Physical RSS  — polled via /proc/self/status (cgroups are ignored under
                    rootless runsc --ignore-cgroups). Guest budget already
                    excludes systrap overhead (see oci.py).
  - Virtual AS    — RLIMIT_AS (mmap / file-backed maps may exceed RSS).
  - PIDs / CPU    — RLIMIT_NPROC / RLIMIT_CPU.

Limits are injected via /run/sandbox/config.json by oci.py at bundle build
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
import signal
import struct
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("sandbox.server")

CONFIG_PATH = Path("/run/sandbox/config.json")

# Physical RSS cap (bytes). 0 = disabled.
_rss_limit_bytes: int = 0
_rss_exceeded = threading.Event()
_rss_stop = threading.Event()


def _read_rss_bytes() -> int:
    """Return current process RSS in bytes from /proc (0 if unavailable)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024  # kB → bytes
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _on_rss_signal(signum: int, frame: Any) -> None:
    """Raise MemoryError into the main thread when the RSS watchdog fires."""
    mb = _rss_limit_bytes // (1024 * 1024) if _rss_limit_bytes else 0
    raise MemoryError(f"Physical RAM limit exceeded ({mb} MB)")


def _rss_watchdog_loop(limit_bytes: int, interval: float = 0.05) -> None:
    """
    Background thread: poll VmRSS and signal the main thread on breach.

    A thread is required because user code often does large synchronous
    allocations that block the asyncio event loop.
    """
    while not _rss_stop.wait(interval):
        rss = _read_rss_bytes()
        if rss > limit_bytes:
            _rss_exceeded.set()
            logger.error(
                "RSS watchdog: %d MB > limit %d MB — signalling MemoryError",
                rss // (1024 * 1024),
                limit_bytes // (1024 * 1024),
            )
            try:
                os.kill(os.getpid(), signal.SIGUSR1)
            except OSError:
                os._exit(137)
            return


def _rss_over_limit() -> bool:
    if _rss_exceeded.is_set():
        return True
    if _rss_limit_bytes > 0 and _read_rss_bytes() > _rss_limit_bytes:
        _rss_exceeded.set()
        return True
    return False


def _apply_resource_limits(limits: Dict[str, Any]) -> None:
    """
    Apply POSIX + RSS-watchdog limits from the config injected by oci.py.

    Works regardless of --ignore-cgroups:
      RLIMIT_AS    — virtual address space (mmap headroom).
      RSS watchdog — physical RAM (VmRSS).
      RLIMIT_NPROC — max processes/threads.
      RLIMIT_CPU   — max CPU seconds.
    """
    global _rss_limit_bytes

    vas_bytes = limits.get("virtual_memory_bytes") or 0
    if vas_bytes and vas_bytes > 0:
        try:
            resource.setrlimit(resource.RLIMIT_AS, (vas_bytes, vas_bytes))
            logger.info(
                "RLIMIT_AS (virtual) set to %d MB",
                vas_bytes // (1024 * 1024),
            )
        except (ValueError, resource.error) as exc:
            logger.warning("Failed to set RLIMIT_AS: %s", exc)

    memory_bytes = limits.get("memory_bytes") or 0
    if memory_bytes and memory_bytes > 0:
        _rss_limit_bytes = int(memory_bytes)
        _rss_exceeded.clear()
        _rss_stop.clear()
        try:
            signal.signal(signal.SIGUSR1, _on_rss_signal)
        except (ValueError, OSError) as exc:
            logger.warning("Failed to install SIGUSR1 handler: %s", exc)
        threading.Thread(
            target=_rss_watchdog_loop,
            args=(_rss_limit_bytes,),
            name="rss-watchdog",
            daemon=True,
        ).start()
        logger.info(
            "RSS watchdog armed at %d MB (guest physical RAM cap)",
            _rss_limit_bytes // (1024 * 1024),
        )

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

        if _rss_over_limit():
            mb = _rss_limit_bytes // (1024 * 1024)
            return {
                "status": "error",
                "error": f"MemoryError: Physical RAM limit exceeded ({mb} MB)",
            }

        ns["res"] = res

        if postprocessing_code:
            exec(postprocessing_code, ns)
            res = ns.get("res", res)

        if _rss_over_limit():
            mb = _rss_limit_bytes // (1024 * 1024)
            return {
                "status": "error",
                "error": f"MemoryError: Physical RAM limit exceeded ({mb} MB)",
            }

        return {"status": "ok", "result": res}

    except MemoryError as exc:
        logger.error("Physical RAM limit hit: %s", exc)
        return {"status": "error", "error": f"MemoryError: {exc}"}
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("User code execution exception: %s\n%s", exc, tb)
        error_msg = f"{type(exc).__name__}: {str(exc)[:500]}"
        return {"status": "error", "error": error_msg}


async def main() -> None:
    """Read length-prefixed JSON requests from stdin, write responses to stdout."""
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
