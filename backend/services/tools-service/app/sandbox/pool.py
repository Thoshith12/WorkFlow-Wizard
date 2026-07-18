"""
app.sandbox.pool — SandboxPool (Redis-backed container registry).

Manages warm gVisor containers — one per custom tool. Responsibilities:
  - Boot containers on first request (with Redis distributed lock + heartbeat).
  - Host-scoped registry keys for horizontal scaling.
  - Liveness probe (socket check) with hot-path optimization.
  - Dead-socket detection → invalidate + rebuild.
  - Idle timeout reaping (called by Celery Beat).
  - Graceful shutdown.

Registry key format: tools_sandbox_registry:{hostname}:{tool_name}@{tool_version}
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket as socket_mod
import time
from typing import Any, Dict, Optional

from app.config.tool_settings import tool_settings
from app.models.custom_tool import CustomTool

logger = logging.getLogger(__name__)

_HOSTNAME = socket_mod.gethostname()


class SandboxPool:
    """
    Redis-backed registry of warm gVisor containers.

    Each entry maps a tool key to its Unix socket path and metadata.
    """

    def __init__(self) -> None:
        self._local_cache: Dict[str, Dict[str, Any]] = {}
        self._boot_locks: Dict[str, asyncio.Lock] = {}

    def _registry_key(self, tool_name: str, tool_version: str) -> str:
        """Host-scoped Redis key for horizontal scaling."""
        return f"tools_sandbox_registry:{_HOSTNAME}:{tool_name}@{tool_version}"

    async def _get_redis(self):
        """Get the Redis client from the shared ServerManager."""
        from shared.database import server_manager
        return await server_manager.get_adapter("redis").get_client()

    async def get_or_start(self, tool: CustomTool) -> str:
        """
        Return the Unix socket path for a warm container.

        If no container exists or the existing one is dead, boot a new one.
        Uses a per-tool asyncio lock to prevent double-booting.
        """
        tool_key = f"{tool.name}@{tool.version}"
        reg_key = self._registry_key(tool.name, tool.version)

        # Check local cache first (hot path — skip liveness probe if recent)
        cached = self._local_cache.get(tool_key)
        if cached:
            last_active = cached.get("last_active", 0)
            if time.time() - last_active < 1.0:
                return cached["socket_path"]

            # Liveness probe on cached entry
            if await self._socket_alive(cached["socket_path"]):
                cached["last_active"] = time.time()
                return cached["socket_path"]
            else:
                logger.warning("Dead socket for %s, invalidating.", tool_key)
                await self.invalidate(tool.name, tool.version)

        # Check Redis registry
        redis = await self._get_redis()
        entry_raw = await redis.get(reg_key)
        if entry_raw:
            entry = json.loads(entry_raw)
            socket_path = entry["socket_path"]
            if await self._socket_alive(socket_path):
                self._local_cache[tool_key] = {
                    "socket_path": socket_path,
                    "last_active": time.time(),
                    **entry,
                }
                return socket_path
            else:
                logger.warning("Dead socket in Redis for %s, invalidating.", tool_key)
                await self._cleanup_entry(tool_key, reg_key)

        # Boot new container (with lock to prevent double-boot)
        if tool_key not in self._boot_locks:
            self._boot_locks[tool_key] = asyncio.Lock()

        async with self._boot_locks[tool_key]:
            # Double-check after acquiring lock
            cached = self._local_cache.get(tool_key)
            if cached and await self._socket_alive(cached["socket_path"]):
                return cached["socket_path"]

            return await self._boot_with_lock(tool, tool_key, reg_key)

    async def _boot_with_lock(
        self, tool: CustomTool, tool_key: str, reg_key: str
    ) -> str:
        """
        Boot a new gVisor container for the given tool.

        Uses a Redis distributed lock with heartbeat to prevent orphaned
        duplicate containers when boot takes longer than the lock TTL.
        """
        redis = await self._get_redis()
        lock_key = f"tools_sandbox_boot_lock:{_HOSTNAME}:{tool_key}"
        lock_ttl = 30  # seconds

        # Acquire Redis lock
        acquired = await redis.set(lock_key, "1", nx=True, ex=lock_ttl)
        if not acquired:
            # Another process is booting — wait and retry
            logger.info("Waiting for boot lock on %s...", tool_key)
            for _ in range(lock_ttl):
                await asyncio.sleep(1)
                entry_raw = await redis.get(reg_key)
                if entry_raw:
                    entry = json.loads(entry_raw)
                    self._local_cache[tool_key] = {
                        **entry,
                        "last_active": time.time(),
                    }
                    return entry["socket_path"]
            raise RuntimeError(f"Timed out waiting for boot lock on {tool_key}")

        # Lock heartbeat task — extends TTL during long boots
        heartbeat_task = asyncio.create_task(
            self._lock_heartbeat(redis, lock_key, lock_ttl)
        )

        try:
            # Build venv if needed
            from app.sandbox.venv_cache import venv_cache
            venv_path = await venv_cache.get_or_build(
                requirements=tool.requirements or [],
                venv_hash=tool.venv_hash,
            )

            # Build OCI bundle
            from app.sandbox.oci import build_oci_bundle
            bundle_path, socket_path = await build_oci_bundle(
                tool=tool,
                venv_path=venv_path,
            )

            # Start gVisor container
            from app.sandbox.netfilter import apply_iptables_rules
            container_id = f"tool-sandbox-{tool.name}-{tool.version}-{_HOSTNAME}"

            proc = await asyncio.create_subprocess_exec(
                "runsc", "run",
                "--rootless",
                "--network=host",
                "--bundle", str(bundle_path),
                container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for the socket to become available
            for attempt in range(30):
                await asyncio.sleep(0.5)
                if await self._socket_alive(socket_path):
                    break
            else:
                raise RuntimeError(f"Container socket never became available: {tool_key}")

            # Apply iptables rules for network isolation
            await apply_iptables_rules(container_id)

            # Register in Redis
            entry = {
                "socket_path": str(socket_path),
                "container_id": container_id,
                "pid": proc.pid,
                "boot_time": time.time(),
                "request_count": 0,
            }
            await redis.set(reg_key, json.dumps(entry), ex=tool_settings.sandbox.max_lifetime_seconds)

            # Update local cache
            self._local_cache[tool_key] = {**entry, "last_active": time.time()}

            logger.info("Booted sandbox container for %s (pid=%s)", tool_key, proc.pid)
            return str(socket_path)

        finally:
            heartbeat_task.cancel()
            await redis.delete(lock_key)

    async def _lock_heartbeat(self, redis, lock_key: str, ttl: int) -> None:
        """
        Extend the Redis boot lock TTL periodically to prevent orphaned
        duplicate containers when boot takes longer than expected.
        """
        interval = ttl // 2
        try:
            while True:
                await asyncio.sleep(interval)
                await redis.expire(lock_key, ttl)
        except asyncio.CancelledError:
            pass

    async def _socket_alive(self, socket_path: str) -> bool:
        """Quick liveness probe — open and immediately close a Unix connection."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(socket_path),
                timeout=1.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def _cleanup_entry(self, tool_key: str, reg_key: str) -> None:
        """Remove a dead entry from both local cache and Redis."""
        self._local_cache.pop(tool_key, None)
        try:
            redis = await self._get_redis()
            await redis.delete(reg_key)
        except Exception as exc:
            logger.warning("Failed to clean Redis entry %s: %s", reg_key, exc)

    async def invalidate(self, tool_name: str, tool_version: str) -> None:
        """
        Stop and remove a container for a tool.

        Called when:
          - requirements/imports/config change (PATCH)
          - tool is deleted
          - dead socket detected
        """
        tool_key = f"{tool_name}@{tool_version}"
        reg_key = self._registry_key(tool_name, tool_version)

        cached = self._local_cache.pop(tool_key, None)
        if cached and "container_id" in cached:
            container_id = cached["container_id"]
            try:
                # Remove iptables rules first (exact match deletion)
                from app.sandbox.netfilter import remove_iptables_rules
                await remove_iptables_rules(container_id)

                # Kill the container
                proc = await asyncio.create_subprocess_exec(
                    "runsc", "kill", container_id, "SIGKILL",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()

                # Delete the container
                proc = await asyncio.create_subprocess_exec(
                    "runsc", "delete", "--force", container_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                logger.info("Stopped container %s for %s", container_id, tool_key)
            except Exception as exc:
                logger.warning("Error stopping container %s: %s", container_id, exc)

        try:
            redis = await self._get_redis()
            await redis.delete(reg_key)
        except Exception as exc:
            logger.warning("Failed to delete Redis key %s: %s", reg_key, exc)

    async def reap_idle(self) -> int:
        """
        Reap idle containers. Called by the in-process asyncio reaper background task.

        Only iterates _local_cache, which contains only containers booted by this
        process — so reaping is inherently host-scoped. A runsc kill/delete for a
        container on a different replica would fail harmlessly (no such container),
        but that cannot happen here since we never reap keys we didn't register.

        Returns the number of containers reaped.
        """
        reaped = 0
        now = time.time()
        idle_threshold = tool_settings.sandbox.idle_timeout_seconds

        for tool_key, entry in list(self._local_cache.items()):
            last_active = entry.get("last_active", 0)
            if now - last_active > idle_threshold:
                parts = tool_key.split("@")
                if len(parts) == 2:
                    await self.invalidate(parts[0], parts[1])
                    reaped += 1

        if reaped:
            logger.info("Reaped %d idle sandbox containers.", reaped)
        return reaped

    async def shutdown(self) -> None:
        """Stop all containers on graceful shutdown."""
        for tool_key in list(self._local_cache.keys()):
            parts = tool_key.split("@")
            if len(parts) == 2:
                await self.invalidate(parts[0], parts[1])
        logger.info("SandboxPool shut down — all containers stopped.")


# Module-level singleton
sandbox_pool = SandboxPool()
