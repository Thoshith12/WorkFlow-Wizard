"""
app.sandbox.server — Sandboxed execution server running inside gVisor container.

Reads execution request payloads from sys.stdin.buffer, executes user code in an
isolated namespace, and writes length-prefixed JSON responses to sys.stdout.buffer.
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

logger = logging.getLogger("sandbox.server")

CONFIG_PATH = Path("/run/sandbox/config.json")


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
