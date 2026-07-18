"""
app.sandbox.oci — OCI bundle builder for gVisor containers.

Builds the filesystem layout and config.json that gVisor's `runsc run`
expects. Each tool gets its own bundle with:
  - Read-only rootfs (Python base image)
  - Read-only venv mount (per-tool, from disk cache)
  - tmpfs at /tmp (size-limited)
  - Config JSON written to /run/sandbox/config.json
  - The sandbox server.py as the container entrypoint
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Tuple

from app.config.tool_settings import tool_settings
from app.models.custom_tool import CustomTool

logger = logging.getLogger(__name__)

BUNDLES_DIR = Path("/tmp/tool-bundles")


async def build_oci_bundle(
    *,
    tool: CustomTool,
    venv_path: Path,
) -> Tuple[Path, Path]:
    """
    Build an OCI bundle directory for the given tool.

    Returns:
        (bundle_path, socket_path) — the bundle directory and the Unix
        socket path where the in-container server will listen.
    """
    cfg = tool_settings.sandbox
    tool_key = f"{tool.name}-{tool.version}"
    bundle_path = BUNDLES_DIR / tool_key
    rootfs_path = bundle_path / "rootfs"

    # Clean previous bundle
    if bundle_path.exists():
        shutil.rmtree(bundle_path, ignore_errors=True)

    bundle_path.mkdir(parents=True, exist_ok=True)
    rootfs_path.mkdir(parents=True, exist_ok=True)

    # Socket path (accessible from host via bind mount)
    socket_dir = bundle_path / "sockets"
    socket_dir.mkdir(parents=True, exist_ok=True)
    socket_path = socket_dir / "tool.sock"

    # Write config.json for the tool (config key-values)
    run_sandbox_dir = rootfs_path / "run" / "sandbox"
    run_sandbox_dir.mkdir(parents=True, exist_ok=True)

    config_json_path = run_sandbox_dir / "config.json"
    config_json_path.write_text(json.dumps(tool.config or {}))

    # Copy server.py into the rootfs
    server_src = Path(__file__).parent / "server.py"
    server_dest = run_sandbox_dir / "server.py"
    shutil.copy2(server_src, server_dest)

    # ── OCI config.json (runtime spec) ────────────────────────────────────
    oci_config = {
        "ociVersion": "1.0.0",
        "process": {
            "terminal": False,
            "user": {"uid": 65534, "gid": 65534},  # nobody
            "args": [
                "python3", "-u", "/run/sandbox/server.py",
            ],
            "env": [
                "PATH=/usr/local/bin:/usr/bin:/bin",
                f"SANDBOX_SOCKET_PATH=/run/sandbox/tool.sock",
                "PYTHONDONTWRITEBYTECODE=1",
                "PYTHONUNBUFFERED=1",
            ],
            "cwd": "/",
            "rlimits": [
                {"type": "RLIMIT_NOFILE", "hard": 1024, "soft": 1024},
            ],
        },
        "root": {
            "path": str(rootfs_path),
            "readonly": True,
        },
        "mounts": [
            {
                "destination": "/proc",
                "type": "proc",
                "source": "proc",
            },
            {
                "destination": "/tmp",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": [f"size={cfg.tmpfs_size_mb}m", "nosuid", "nodev", "noexec"],
            },
            {
                "destination": "/opt/venv",
                "type": "bind",
                "source": str(venv_path),
                "options": ["rbind", "ro"],
            },
            {
                "destination": "/run/sandbox",
                "type": "bind",
                "source": str(run_sandbox_dir),
                "options": ["rbind", "ro"],
            },
            {
                "destination": "/run/sandbox/tool.sock",
                "type": "bind",
                "source": str(socket_path),
                "options": ["rbind", "rw"],
            },
        ],
        "linux": {
            "resources": {
                "memory": {
                    "limit": cfg.memory_mb * 1024 * 1024,
                },
                "cpu": {
                    "quota": cfg.cpu_quota_percent * 1000,
                    "period": 100000,
                },
                "pids": {
                    "limit": cfg.pids_limit,
                },
            },
            "namespaces": [
                {"type": "pid"},
                {"type": "ipc"},
                {"type": "uts"},
                {"type": "mount"},
                {"type": "network"},
            ],
        },
    }

    config_path = bundle_path / "config.json"
    config_path.write_text(json.dumps(oci_config, indent=2))

    logger.info("Built OCI bundle for %s at %s", tool_key, bundle_path)
    return bundle_path, socket_path
