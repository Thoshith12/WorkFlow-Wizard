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
import shutil
from pathlib import Path
from typing import Any, Dict

from app.config.tool_settings import tool_settings
from app.models.custom_tool import CustomTool

logger = logging.getLogger(__name__)

BUNDLES_DIR = Path("/tmp/tool-bundles")


async def build_oci_bundle(
    tool: CustomTool,
    venv_path: Path,
    port: int,
) -> Path:
    """
    Build an OCI bundle directory for the given tool.

    The in-container server listens on loopback TCP `port` (not a Unix socket —
    gVisor virtualizes AF_UNIX away under --network=host; see server.py).

    Returns:
        bundle_path — the bundle directory `runsc run --bundle` consumes.
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

    # Write config.json for the tool (config key-values) plus _sandbox_limits
    # so server.py can enforce resource limits via POSIX setrlimit at startup.
    # This works even when runsc runs with --ignore-cgroups (rootless Docker).
    run_sandbox_dir = rootfs_path / "run" / "sandbox"
    run_sandbox_dir.mkdir(parents=True, exist_ok=True)
    import os
    os.chmod(str(run_sandbox_dir), 0o777)

    # Guest RSS budget = total host budget minus systrap/sentry overhead.
    # Host-side watchdog on the runsc PID still enforces memory_mb in full.
    guest_memory_mb = max(64, cfg.memory_mb - cfg.runtime_overhead_mb)

    tool_config = dict(tool.config or {})
    tool_config["_sandbox_limits"] = {
        # Physical RSS cap inside the guest (bytes). Enforced by server.py
        # RSS watchdog — cgroups are ignored under rootless --ignore-cgroups.
        "memory_bytes": guest_memory_mb * 1024 * 1024,
        # Virtual address space cap (RLIMIT_AS). Allows mmap/file maps up to
        # this size without requiring that much physical RAM.
        "virtual_memory_bytes": cfg.virtual_memory_mb * 1024 * 1024,
        # RLIMIT_NPROC: max processes/threads the sandbox can spawn.
        "pids_limit": cfg.pids_limit,
        # RLIMIT_CPU: CPU seconds before SIGXCPU is raised.
        # Use exec_timeout as the ceiling — sandbox code cannot run longer.
        "cpu_seconds": cfg.exec_timeout_seconds,
    }
    config_json_path = run_sandbox_dir / "config.json"
    config_json_path.write_text(json.dumps(tool_config))

    # Copy server.py into the rootfs
    server_src = Path(__file__).parent / "server.py"
    server_dest = run_sandbox_dir / "server.py"
    shutil.copy2(server_src, server_dest)

    # ── OCI config.json (runtime spec) ────────────────────────────────────
    oci_config = {
        "ociVersion": "1.0.0",
        "process": {
            "terminal": False,
            "user": {"uid": cfg.sandbox_uid, "gid": cfg.sandbox_gid},  # nobody
            "args": [
                "python3", "-u", "/run/sandbox/server.py",
            ],
            "env": [
                # python3 resolves from the bind-mounted /usr/local/bin (see mounts
                # below) — the real, standard interpreter, not anything venv-provided.
                "PATH=/usr/local/bin:/usr/bin:/bin",
                # Extra pip packages from the per-tool venv (site-packages only —
                # the venv supplies no interpreter of its own in this design).
                "PYTHONPATH=/opt/venv/lib/python3.11/site-packages",
                f"SANDBOX_PORT={port}",
                "PYTHONDONTWRITEBYTECODE=1",
                "PYTHONUNBUFFERED=1",
                # Allow HuggingFace/fastembed model caches to write to writable tmpfs.
                "HOME=/tmp",
                "HF_HOME=/tmp/hf_cache",
                "FASTEMBED_CACHE_PATH=/tmp/fastembed_cache",
                # SSL certificate locations — required for HTTPS (HuggingFace, PyPI).
                # gVisor's internal reqwest TLS client reads SSL_CERT_FILE/DIR.
                "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt",
                "SSL_CERT_DIR=/etc/ssl/certs",
                "REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt",
                "CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt",
            ],
            "cwd": "/",
            "rlimits": [
                {"type": "RLIMIT_NOFILE", "hard": 1024, "soft": 1024},
                # VAS ceiling (not RSS). Physical RAM is enforced in server.py.
                {
                    "type": "RLIMIT_AS",
                    "hard": cfg.virtual_memory_mb * 1024 * 1024,
                    "soft": cfg.virtual_memory_mb * 1024 * 1024,
                },
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
                "options": ["rbind", "ro", "exec"],
            },
            # The sandbox rootfs has no base OS/Python install of its own (by
            # design — no full image per tool). These three give every custom
            # tool a real, standard Python 3.11 runtime (interpreter + stdlib +
            # its shared library dependencies) for free, reusing exactly what's
            # already installed in this container. The per-tool venv above only
            # needs to supply extra pip packages (via PYTHONPATH below), not its
            # own interpreter.
            {
                "destination": "/usr/local",
                "type": "bind",
                "source": "/usr/local",
                "options": ["rbind", "ro"],
            },
            {
                "destination": "/lib",
                "type": "bind",
                "source": "/lib",
                "options": ["rbind", "ro"],
            },
            {
                "destination": "/lib64",
                "type": "bind",
                "source": "/lib64",
                "options": ["rbind", "ro"],
            },
            {
                "destination": "/run/sandbox",
                "type": "bind",
                "source": str(run_sandbox_dir),
                "options": ["rbind", "rw"],
            },
            # Mount host DNS config so the sandbox can resolve external hostnames
            # (HuggingFace, PyPI, etc.) while iptables owner rules still block
            # RFC-1918 internal subnets (see netfilter.py).
            {
                "destination": "/etc/resolv.conf",
                "type": "bind",
                "source": "/etc/resolv.conf",
                "options": ["rbind", "ro"],
            },
            {
                "destination": "/etc/hosts",
                "type": "bind",
                "source": "/etc/hosts",
                "options": ["rbind", "ro"],
            },
            # Mount host CA certificates so HTTPS connections (HuggingFace, PyPI)
            # succeed inside the sandbox. Without this, TLS verification fails
            # with gVisor's reqwest "builder error" (no trust anchors found).
            {
                "destination": "/etc/ssl/certs",
                "type": "bind",
                "source": "/etc/ssl/certs",
                "options": ["rbind", "ro"],
            },
        ],
        "linux": {
            "resources": {
                "memory": {
                    # Full host budget (incl. overhead). Honored only when
                    # cgroups are not ignored; guest+host watchdogs are primary.
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
                # NOTE: network namespace intentionally omitted — rootless gVisor
                # runs with --network=host which shares the host network namespace.
                # A 'network' ns entry here is a no-op with --network=host and
                # would conflict with /etc/resolv.conf DNS resolution.
                # Internet access is permitted; internal RFC-1918 subnets are
                # blocked via iptables OUTPUT rules scoped to the sandbox uid
                # (see netfilter.py apply_iptables_rules).
            ],
        },
    }

    config_path = bundle_path / "config.json"
    config_path.write_text(json.dumps(oci_config, indent=2))

    logger.info("Built OCI bundle for %s at %s", tool_key, bundle_path)
    return bundle_path
