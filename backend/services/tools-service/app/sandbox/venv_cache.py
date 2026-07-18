"""
app.sandbox.venv_cache — Disk-cached per-tool venv builder.

Builds virtual environments keyed by sha256(sorted(requirements)).
If the venv for a given hash already exists on disk, it is reused.
Venvs are mounted read-only into gVisor containers.

Cache directory: /tmp/tool-venvs/{hash}/
LRU eviction: when cache exceeds SANDBOX_VENV_CACHE_SIZE entries.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from app.config.tool_settings import tool_settings

logger = logging.getLogger(__name__)

VENV_CACHE_DIR = Path("/tmp/tool-venvs")


class VenvCache:
    """
    LRU disk-cached venv builder.

    Keyed by sha256 of sorted requirements — tools with identical
    requirements share a venv (read-only mount).
    """

    def __init__(self) -> None:
        self._max_size = tool_settings.sandbox.venv_cache_size
        self._build_locks: dict[str, asyncio.Lock] = {}
        VENV_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _hash_requirements(self, requirements: List[str]) -> str:
        """Compute sha256 of sorted requirements for cache key."""
        reqs = sorted(requirements)
        return hashlib.sha256("|".join(reqs).encode()).hexdigest()

    async def get_or_build(
        self,
        requirements: List[str],
        venv_hash: Optional[str] = None,
    ) -> Path:
        """
        Return the path to a venv with the given requirements installed.

        If the venv exists on disk (cache hit), return immediately.
        If not, build it (pip install into a fresh venv) and cache.
        """
        if not requirements:
            # No requirements — return a minimal venv
            return await self._get_or_build_empty()

        req_hash = venv_hash or self._hash_requirements(requirements)
        venv_path = VENV_CACHE_DIR / req_hash

        if venv_path.exists() and (venv_path / "pyvenv.cfg").exists():
            logger.debug("Venv cache hit for %s", req_hash[:12])
            return venv_path

        # Build lock per hash to prevent duplicate builds
        if req_hash not in self._build_locks:
            self._build_locks[req_hash] = asyncio.Lock()

        async with self._build_locks[req_hash]:
            # Double-check after acquiring lock
            if venv_path.exists() and (venv_path / "pyvenv.cfg").exists():
                return venv_path

            logger.info("Building venv for hash %s (%d packages)...", req_hash[:12], len(requirements))
            await self._build_venv(venv_path, requirements)
            await self._evict_if_needed()
            return venv_path

    async def _get_or_build_empty(self) -> Path:
        """Return a minimal empty venv (no extra packages)."""
        venv_path = VENV_CACHE_DIR / "empty"
        if venv_path.exists():
            return venv_path

        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "venv", str(venv_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to create empty venv: {stderr.decode()}")
        return venv_path

    async def _build_venv(self, venv_path: Path, requirements: List[str]) -> None:
        """Create a venv and pip install requirements into it."""
        # Create venv
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "venv", str(venv_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to create venv: {stderr.decode()}")

        # Write requirements file
        req_file = venv_path / "requirements.txt"
        req_file.write_text("\n".join(requirements))

        # pip install
        pip_path = venv_path / "bin" / "pip"
        proc = await asyncio.create_subprocess_exec(
            str(pip_path), "install", "--no-cache-dir", "-r", str(req_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            # Clean up failed venv
            shutil.rmtree(venv_path, ignore_errors=True)
            raise RuntimeError(
                f"pip install failed for venv: {stderr.decode()[:500]}"
            )

        logger.info("Built venv %s with %d packages.", venv_path.name[:12], len(requirements))

    async def _evict_if_needed(self) -> None:
        """LRU eviction — remove oldest venvs when cache exceeds max size."""
        if not VENV_CACHE_DIR.exists():
            return

        entries = sorted(
            [p for p in VENV_CACHE_DIR.iterdir() if p.is_dir() and p.name != "empty"],
            key=lambda p: p.stat().st_mtime,
        )

        while len(entries) > self._max_size:
            oldest = entries.pop(0)
            logger.info("Evicting venv cache entry: %s", oldest.name[:12])
            shutil.rmtree(oldest, ignore_errors=True)


# Module-level singleton
venv_cache = VenvCache()
