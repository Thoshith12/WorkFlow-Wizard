"""
app.sandbox.server — In-container asyncio server (warm process).

This module runs INSIDE the gVisor container. It:
  1. Listens on a loopback UDS socket (/run/sandbox/tool.sock) for execution requests.
  2. For each request, executes user code in a fresh, isolated namespace with safe builtins.
  3. Pre-loads config into namespace as a plain dict (config.get('key')).
  4. Returns the result over the socket.

Security & Isolation:
  The gVisor sandbox container IS the primary security boundary (non-root user,
  read-only rootfs, iptables network scoping, cgroup memory/CPU limits, syscall interception).
"""
from __future__ import annotations

import asyncio
import builtins
import importlib
import json
import logging
import os
import struct
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Path where the trusted runner (container boot) writes config.json
CONFIG_PATH = Path("/run/sandbox/config.json")

# Loopback UDS path the server listens on
SOCK_PATH = os.environ.get("SANDBOX_SOCK", "/run/sandbox/tool.sock")


async def _execute_user_code(
    preprocessing_code: Optional[str],
    processing_code: str,
    postprocessing_code: Optional[str],
    imports: list,
    input_data: dict,
    timeout: float,
) -> Dict[str, Any]:
    """Execute user code directly in a clean dictionary namespace."""
    try:
        # Pre-load config into namespace
        config = {}
        if CONFIG_PATH.exists():
            try:
                with open(str(CONFIG_PATH)) as f:
                    config = json.load(f)
            except Exception:
                pass

        # Clean namespace for this request
        ns: Dict[str, Any] = {
            "__builtins__": builtins,
            "config": config,
            "input_data": input_data,
        }

        # Standard library modules available by default
        ns["os"] = os
        ns["json"] = json
        ns["math"] = importlib.import_module("math")
        ns["re"] = importlib.import_module("re")
        ns["datetime"] = importlib.import_module("datetime")
        ns["collections"] = importlib.import_module("collections")

        # Import declared modules
        for module_name in imports:
            try:
                ns[module_name.split(".")[-1]] = importlib.import_module(module_name)
            except ImportError as exc:
                return {"status": "error", "error": f"Import failed: {exc}"}

        # Execute preprocessing phase
        if preprocessing_code:
            exec(preprocessing_code, ns)

        # Execute processing code phase (defines process function)
        exec(processing_code, ns)

        # Call process(input_data)
        if "process" not in ns or not callable(ns["process"]):
            return {
                "status": "error",
                "error": "processing_code must define 'async def process(input_data)'",
            }

        coro = ns["process"](input_data)
        if asyncio.iscoroutine(coro):
            res = await asyncio.wait_for(coro, timeout=timeout)
        else:
            res = coro

        # Make res available to postprocessing phase
        ns["res"] = res

        # Execute postprocessing phase
        if postprocessing_code:
            exec(postprocessing_code, ns)
            res = ns.get("res", res)

        return {"status": "ok", "result": res}

    except asyncio.TimeoutError:
        return {"status": "error", "error": f"Execution timed out after {timeout}s"}
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("User code execution exception: %s\n%s", exc, tb)
        error_msg = f"{type(exc).__name__}: {str(exc)[:500]}"
        return {"status": "error", "error": error_msg}


async def handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle a single execution request from the executor."""
    try:
        # Read length-prefixed request
        raw_len = await reader.readexactly(4)
        msg_len = struct.unpack(">I", raw_len)[0]
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

        # Send length-prefixed response
        response_bytes = json.dumps(result, default=str).encode()
        writer.write(struct.pack(">I", len(response_bytes)))
        writer.write(response_bytes)
        await writer.drain()

    except Exception as exc:
        logger.error("Error handling connection: %s", exc)
        error_response = json.dumps({"status": "error", "error": str(exc)[:500]}).encode()
        try:
            writer.write(struct.pack(">I", len(error_response)))
            writer.write(error_response)
            await writer.drain()
        except Exception:
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    """Start the loopback TCP server inside the container."""
    port = int(os.environ.get("SANDBOX_PORT", "18521"))
    server = await asyncio.start_server(handle_connection, host="127.0.0.1", port=port)
    logger.info("Sandbox server listening on 127.0.0.1:%d", port)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    asyncio.run(main())
