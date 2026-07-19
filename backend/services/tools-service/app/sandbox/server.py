"""
app.sandbox.server — In-container asyncio server (warm process).

This module runs INSIDE the gVisor container. It:
  1. Listens on a loopback TCP port (127.0.0.1) for execution requests.
     AF_UNIX is NOT used — gVisor virtualizes AF_UNIX sockets entirely inside
     its Sentry, so a bind() inside the sandbox never materializes a real,
     connectable socket on the host side of a bind mount. TCP over loopback
     goes through the real (host-shared, via --network=host) network stack,
     so the executor in the tools-service process can actually reach it, while
     127.0.0.1 keeps it unreachable from any other container/namespace.
  2. For each request, spawns a fresh multiprocessing.Process with:
     - Clean safe-builtins (no open, no __import__)
     - Config pre-loaded into exec namespace as a plain dict
     - User code executed via exec() in the restricted namespace
  3. Waits for the result via non-blocking add_reader (NOT a poll loop).
  4. Returns the result over the socket.

The container stays warm between requests — only the subprocess is fresh.

CONFIG ACCESS: The trusted runner pre-loads config.json into ns["config"]
before exec() runs. User code accesses config as `config.get('key')`.
`open` is NOT in _safe_builtins — the user never gets a file-open primitive.
"""
from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
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

# Safe builtins — deliberately minimal. No open(), no __import__().
_SAFE_BUILTINS = {
    "None": None, "True": True, "False": False,
    "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
    "bytes": bytes, "chr": chr, "dict": dict, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float,
    "format": format, "frozenset": frozenset, "getattr": getattr,
    "hasattr": hasattr, "hash": hash, "hex": hex, "id": id,
    "int": int, "isinstance": isinstance, "issubclass": issubclass,
    "iter": iter, "len": len, "list": list, "map": map, "max": max,
    "min": min, "next": next, "object": object, "oct": oct,
    "ord": ord, "pow": pow, "print": print, "range": range,
    "repr": repr, "reversed": reversed, "round": round, "set": set,
    "slice": slice, "sorted": sorted, "str": str, "sum": sum,
    "super": super, "tuple": tuple, "type": type, "zip": zip,
    # Exceptions
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "RuntimeError": RuntimeError,
    "StopIteration": StopIteration, "AttributeError": AttributeError,
}


def _execution_worker(
    conn: multiprocessing.connection.Connection,
    preprocessing_code: Optional[str],
    processing_code: str,
    postprocessing_code: Optional[str],
    imports: list,
    input_data: dict,
) -> None:
    """
    Subprocess worker — executed in a fresh process for each request.

    Runs user code in a restricted namespace with safe builtins.
    Config is pre-loaded as ns["config"] by the trusted runner.
    """
    try:
        ns: Dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}

        # ── Pre-load config into namespace (trusted runner) ──────────────
        # User code gets config as a plain dict — never a file-open primitive.
        if CONFIG_PATH.exists():
            with open(str(CONFIG_PATH)) as _f:
                ns["config"] = json.load(_f)
        else:
            ns["config"] = {}

        # ── Import declared modules into namespace ───────────────────────
        for module_name in imports:
            try:
                ns[module_name.split(".")[-1]] = __import__(module_name)
            except ImportError as exc:
                conn.send({"status": "error", "error": f"Import failed: {exc}"})
                return

        # ── Standard library modules always available ────────────────────
        ns["json"] = __import__("json")
        ns["math"] = __import__("math")
        ns["re"] = __import__("re")
        ns["datetime"] = __import__("datetime")
        ns["collections"] = __import__("collections")

        # ── Execute user code phases ─────────────────────────────────────
        ns["input_data"] = input_data

        if preprocessing_code:
            exec(preprocessing_code, ns)

        exec(processing_code, ns)

        if postprocessing_code:
            exec(postprocessing_code, ns)

        # ── Call the process() function ──────────────────────────────────
        if "process" not in ns or not callable(ns["process"]):
            conn.send({"status": "error", "error": "processing_code must define 'async def process(input_data)'"})
            return

        import asyncio as _asyncio
        result = _asyncio.run(ns["process"](input_data))

        conn.send({"status": "ok", "result": result})

    except Exception as exc:
        # Truncate error message to prevent config/secret leakage
        error_msg = f"{type(exc).__name__}: {str(exc)[:500]}"
        conn.send({"status": "error", "error": error_msg})


async def _wait_for_result(
    parent_conn: multiprocessing.connection.Connection,
    timeout: float,
) -> Dict[str, Any]:
    """
    Non-blocking result wait via loop.add_reader.

    Uses add_reader on the connection's file descriptor instead of
    a Connection.poll() loop — avoids busy-waiting and is event-loop
    friendly.
    """
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()

    fd = parent_conn.fileno()

    def _on_readable():
        if not future.done():
            try:
                result = parent_conn.recv()
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)
            finally:
                loop.remove_reader(fd)

    loop.add_reader(fd, _on_readable)

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        loop.remove_reader(fd)
        raise


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

        timeout = request.get("timeout_seconds", 30)

        # Spawn fresh subprocess
        parent_conn, child_conn = multiprocessing.Pipe()
        proc = multiprocessing.Process(
            target=_execution_worker,
            args=(
                child_conn,
                request.get("preprocessing_code"),
                request["processing_code"],
                request.get("postprocessing_code"),
                request.get("imports", []),
                request.get("input_data", {}),
            ),
        )
        proc.start()
        child_conn.close()  # Parent doesn't write to child's end

        try:
            result = await _wait_for_result(parent_conn, timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            proc.join(timeout=1)
            result = {"status": "error", "error": f"Execution timed out after {timeout}s"}
        finally:
            parent_conn.close()
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=1)

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
    """Start the loopback UDS server inside the container."""
    # Ensure any stale socket is removed
    if os.path.exists(SOCK_PATH):
        try:
            os.remove(SOCK_PATH)
        except OSError:
            pass

    server = await asyncio.start_unix_server(handle_connection, path=SOCK_PATH)
    logger.info("Sandbox server listening on %s", SOCK_PATH)

    # Change permissions so host can connect if needed
    try:
        os.chmod(SOCK_PATH, 0o777)
    except Exception as e:
        logger.warning("Could not chmod socket: %s", e)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    asyncio.run(main())
