"""
Test script to reproduce and diagnose the NameError in _execution_worker.
Run this inside the tools-service container:
  python3 /tmp/test_sandbox_worker.py
"""
import sys
import json
import multiprocessing

# Simulate what server.py's _execution_worker does
def test_worker(conn, processing_code, input_data):
    try:
        import importlib
        import builtins

        config = {}
        ns = {
            "__builtins__": builtins,
            "config": config,
            "input_data": input_data,
        }
        ns["os"] = importlib.import_module("os")
        ns["json"] = importlib.import_module("json")
        ns["math"] = importlib.import_module("math")
        ns["re"] = importlib.import_module("re")
        ns["datetime"] = importlib.import_module("datetime")
        ns["collections"] = importlib.import_module("collections")

        exec(processing_code, ns)

        if "process" not in ns or not callable(ns["process"]):
            conn.send({"status": "error", "error": "No process() function defined"})
            return

        import asyncio

        async def _runner():
            return await ns["process"](input_data)

        result = asyncio.run(_runner())
        conn.send({"status": "ok", "result": result})

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        conn.send({
            "status": "error",
            "error": f"{type(exc).__name__}: {str(exc)}",
            "traceback": tb,
        })


if __name__ == "__main__":
    processing_code = "async def process(input_data):\n    return {'result': input_data.get('x', 0) * 2}"
    input_data = {"x": 21}

    print(f"Start method: {multiprocessing.get_start_method()}")
    print(f"Python version: {sys.version}")

    parent_conn, child_conn = multiprocessing.Pipe()
    proc = multiprocessing.Process(
        target=test_worker,
        args=(child_conn, processing_code, input_data),
    )
    proc.start()
    child_conn.close()
    proc.join(timeout=15)

    if parent_conn.poll():
        result = parent_conn.recv()
        print(json.dumps(result, indent=2))
    else:
        print("TIMEOUT - no response received")
        print(f"Process alive: {proc.is_alive()}")
        print(f"Exit code: {proc.exitcode}")
