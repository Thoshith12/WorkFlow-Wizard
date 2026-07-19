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
        # Sticky for this process's lifetime once a platform successfully boots a
        # container — avoids re-attempting a known-failing preferred platform (e.g.
        # kvm) on every single container boot. Cleared only by a process restart,
        # which re-probes from tool_settings.sandbox.platform_preferred again.
        self._resolved_platform: Optional[str] = None
        # Warn once per process, not once per boot, when running with the
        # dev-only --TESTONLY-unsafe-nonroot flag active.
        self._warned_unsafe_nested_dev: bool = False
        # `runsc port-forward` subprocess per tool — gVisor's --network=host
        # does not expose a sandbox's own listening sockets to the host
        # directly (confirmed empirically; port-forward is gVisor's own
        # supported bridge). Not Redis-persisted: a subprocess handle can't
        # survive serialization or a tools-service restart, same as `proc`.
        self._port_forward_procs: Dict[str, asyncio.subprocess.Process] = {}
        # Continuously-drained tail of each runsc process's stderr, keyed by
        # pid — nothing else reads stdout/stderr while a container is alive,
        # and an undrained pipe can fill its OS buffer (64KB) and block the
        # child on write() indefinitely. Bounded (last ~2000 bytes) so it
        # doesn't grow unbounded over a long-lived warm container's lifetime.
        self._stderr_tails: Dict[int, bytearray] = {}

    def _registry_key(self, tool_name: str, tool_version: str) -> str:
        """Host-scoped Redis key for horizontal scaling."""
        return f"tools_sandbox_registry:{_HOSTNAME}:{tool_name}@{tool_version}"

    async def _get_redis(self):
        """Get the Redis client from the shared ServerManager."""
        from shared.database import server_manager
        return server_manager.get("redis").client

    async def get_or_start(self, tool: CustomTool) -> str:
        """
        Return the loopback TCP port of a warm container's server.

        If no container exists or the existing one is dead, boot a new one.
        Uses a per-tool asyncio lock to prevent double-booting.
        """
        tool_key = f"{tool.name}@{tool.version}"
        reg_key = self._registry_key(tool.name, tool.version)

        # Check local cache first (hot path — skip liveness probe if recent)
        # Check local cache first
        cached = self._local_cache.get(tool_key)
        if cached:
            bundle_path = cached["bundle_path"]
            sock_path = f"{bundle_path}/run/sandbox/tool.sock"
            if await self._uds_alive(sock_path):
                cached["last_active"] = time.time()
                return bundle_path
            else:
                logger.warning("Dead sandbox socket for %s, invalidating.", tool_key)
                await self.invalidate(tool.name, tool.version)

        # Check Redis registry
        redis = await self._get_redis()
        entry_raw = await redis.get(reg_key)
        if entry_raw:
            entry = json.loads(entry_raw)
            bundle_path = entry["bundle_path"]
            sock_path = f"{bundle_path}/run/sandbox/tool.sock"
            if await self._uds_alive(sock_path):
                self._local_cache[tool_key] = {
                    "last_active": time.time(),
                    **entry,
                }
                return bundle_path
            else:
                logger.warning("Dead sandbox socket in Redis for %s, invalidating.", tool_key)
                await self._cleanup_entry(tool_key, reg_key)

        # Boot new container (with lock to prevent double-boot)
        if tool_key not in self._boot_locks:
            self._boot_locks[tool_key] = asyncio.Lock()

        async with self._boot_locks[tool_key]:
            # Double-check after acquiring lock
            cached = self._local_cache.get(tool_key)
            if cached:
                bundle_path = cached["bundle_path"]
                sock_path = f"{bundle_path}/run/sandbox/tool.sock"
                if await self._uds_alive(sock_path):
                    return bundle_path

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
                    return entry["bundle_path"]
            raise RuntimeError(f"Timed out waiting for boot lock on {tool_key}")

        logger.info("Boot lock acquired for %s", tool_key, extra={"tool_key": tool_key, "step": "lock_acquired"})

        # Lock heartbeat task — extends TTL during long boots
        heartbeat_task = asyncio.create_task(
            self._lock_heartbeat(redis, lock_key, lock_ttl)
        )

        try:
            # Build venv if needed
            logger.info(
                "Building venv for %s", tool_key,
                extra={"tool_key": tool_key, "step": "venv_build_start"},
            )
            from app.sandbox.venv_cache import venv_cache
            venv_path = await venv_cache.get_or_build(
                requirements=tool.requirements or [],
                venv_hash=tool.venv_hash,
            )
            logger.info(
                "venv ready for %s", tool_key,
                extra={"tool_key": tool_key, "step": "venv_build_done", "venv_path": str(venv_path)},
            )

            from app.sandbox.oci import build_oci_bundle
            bundle_path = await build_oci_bundle(
                tool=tool,
                venv_path=venv_path,
            )
            logger.info(
                "OCI bundle ready for %s", tool_key,
                extra={
                    "tool_key": tool_key, "step": "oci_bundle_done", "bundle_path": str(bundle_path),
                },
            )

            # Start gVisor container (falls back to a secondary platform if the
            # preferred one fails to boot — see _boot_container_with_platform_fallback)
            from app.sandbox.netfilter import apply_iptables_rules
            container_id = f"tool-sandbox-{tool.name}-{tool.version}-{_HOSTNAME}"

            platform_used, proc = await self._boot_container_with_platform_fallback(
                bundle_path=bundle_path,
                container_id=container_id,
                tool_key=tool_key,
            )
            logger.info(
                "Container boot succeeded for %s", tool_key,
                extra={
                    "tool_key": tool_key, "step": "container_boot_done",
                    "container_id": container_id, "platform": platform_used, "pid": proc.pid,
                },
            )

            # Apply iptables rules for network isolation
            logger.info(
                "Applying iptables rules for %s", container_id,
                extra={"tool_key": tool_key, "container_id": container_id, "step": "iptables_apply_start"},
            )
            await apply_iptables_rules(container_id)
            logger.info(
                "iptables rules applied for %s", container_id,
                extra={"tool_key": tool_key, "container_id": container_id, "step": "iptables_apply_done"},
            )

            entry = {
                "bundle_path": str(bundle_path),
                "container_id": container_id,
                "pid": proc.pid,
                "platform": platform_used,
                "boot_time": time.time(),
                "request_count": 0,
            }
            await redis.set(reg_key, json.dumps(entry), ex=tool_settings.sandbox.max_lifetime_seconds)

            # Update local cache
            self._local_cache[tool_key] = {**entry, "last_active": time.time()}

            logger.info(
                "Booted sandbox container for %s (pid=%s, platform=%s)",
                tool_key, proc.pid, platform_used,
                extra={
                    "tool_key": tool_key, "step": "boot_complete",
                    "container_id": container_id, "platform": platform_used, "pid": proc.pid, "bundle_path": str(bundle_path),
                },
            )
            return str(bundle_path)

        finally:
            heartbeat_task.cancel()
            await redis.delete(lock_key)
            logger.info(
                "Boot lock released for %s", tool_key,
                extra={"tool_key": tool_key, "step": "lock_released"},
            )

    async def _boot_container(
        self, *, bundle_path, container_id: str, platform: str
    ) -> asyncio.subprocess.Process:
        """Start `runsc run` for one platform. Caller waits for socket liveness."""
        # runsc's usage is `runsc <flags> <subcommand> <subcommand args>` —
        # --rootless/--network/--platform are global flags and must precede
        # the `run` subcommand, not follow it (confirmed via `runsc --help`).
        args = [
            "--rootless",
            "--ignore-cgroups",
            "--network=host",
            "--host-uds=all",
            f"--platform={platform}",
        ]

        if tool_settings.sandbox.unsafe_nested_dev:
            args.append("--TESTONLY-unsafe-nonroot")
            if not self._warned_unsafe_nested_dev:
                self._warned_unsafe_nested_dev = True
                logger.warning(
                    "SANDBOX_UNSAFE_NESTED_DEV is enabled — runsc is passed "
                    "--TESTONLY-unsafe-nonroot, which lets the sentry/gofer reuse the "
                    "host's existing /proc and / instead of their own isolated mount "
                    "namespace. This is a dev-only escape hatch for running gVisor "
                    "nested inside another container and must never be set in a real "
                    "deployment. It does not affect sandboxed-application isolation "
                    "(ptrace/systrap/kvm syscall interception, uid-owner iptables "
                    "scoping) — only the sentry/gofer's own isolation from the host.",
                    extra={"step": "unsafe_nested_dev_active"},
                )

        proc = await asyncio.create_subprocess_exec(
            "runsc",
            *args,
            "run",
            "--bundle", str(bundle_path),
            container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_tail = bytearray()
        self._stderr_tails[proc.pid] = stderr_tail
        asyncio.create_task(self._drain_stream(proc.stdout, bytearray()))
        asyncio.create_task(self._drain_stream(proc.stderr, stderr_tail))
        return proc

    async def _drain_stream(
        self, stream: Optional[asyncio.StreamReader], buffer: bytearray, max_len: int = 2000
    ) -> None:
        if stream is None:
            return
        try:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                logger.info("SANDBOX STREAM: %s", chunk.decode(errors="replace").strip())
                buffer.extend(chunk)
                if len(buffer) > max_len:
                    del buffer[: len(buffer) - max_len]
        except Exception:
            pass

    async def _uds_alive(self, sock_path: str) -> bool:
        """Quick liveness probe — try connecting to the UDS."""
        if not os.path.exists(sock_path):
            return False
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(sock_path),
                timeout=1.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def _wait_for_uds(
        self,
        sock_path: str,
        proc: Optional[asyncio.subprocess.Process] = None,
        attempts: int = 30,
        interval: float = 0.5,
    ) -> bool:
        for _ in range(attempts):
            await asyncio.sleep(interval)
            if proc is not None and proc.returncode is not None:
                return False

            if await self._uds_alive(sock_path):
                return True

        return False

    async def _discard_failed_container(self, proc: asyncio.subprocess.Process, container_id: str) -> bytes:
        """
        Best-effort teardown of a container that failed to boot, before retrying
        with a different platform. Kills the subprocess (it may be hung rather
        than exited — see gVisor's reported kvm-platform shutdown hangs), then
        runs the same kill/delete sequence used in invalidate() to clear any
        runsc-side state so a retry with the same container_id doesn't collide
        with the failed attempt. Returns captured stderr for logging.
        """
        stderr = b""
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        except Exception:
            pass

        for args in (("kill", container_id, "SIGKILL"), ("delete", "--force", container_id)):
            try:
                cleanup_proc = await asyncio.create_subprocess_exec(
                    "runsc", *args,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await cleanup_proc.wait()
            except Exception:
                pass

        return stderr

    async def _boot_container_with_platform_fallback(
        self, *, bundle_path: Path, container_id: str, tool_key: str
    ) -> tuple[str, asyncio.subprocess.Process]:
        """
        Boot the container by walking an ordered platform chain until one boots
        successfully: [platform_preferred] + platform_fallback_chain (e.g.
        kvm -> systrap -> ptrace). Every fallback step is logged loudly
        (logger.error) — a silent fallback to a weaker isolation platform is a
        security regression, not a graceful degradation.

        Once a platform is known to work in this process, every later boot (for
        any tool) uses ONLY that platform — no re-probing the full chain on every
        boot, and no fallback attempt if it later fails for a specific tool: a
        platform that already worked once and later fails indicates a systemic
        problem (device permissions, host config) that retrying other platforms
        won't fix. A full process restart re-probes from platform_preferred again.

        allow_platform_fallback=False restricts the chain to just the first
        platform — failure raises immediately instead of walking the rest.
        """
        cfg = tool_settings.sandbox

        if self._resolved_platform:
            chain = [self._resolved_platform]
            sources = ["resolved"]
        else:
            chain = [cfg.platform_preferred] + [
                p for p in cfg.platform_fallback_chain if p != cfg.platform_preferred
            ]
            sources = ["preferred"] + [f"fallback[{i}]" for i in range(1, len(chain))]

        if not cfg.allow_platform_fallback:
            chain = chain[:1]
            sources = sources[:1]

        last_stderr_text = ""
        for index, (platform, source) in enumerate(zip(chain, sources)):
            logger.info(
                "Attempting sandbox boot on %s platform '%s' for %s",
                source, platform, tool_key,
                extra={
                    "tool_key": tool_key, "container_id": container_id, "step": "platform_attempt",
                    "platform": platform, "platform_source": source,
                },
            )
            proc = await self._boot_container(bundle_path=bundle_path, container_id=container_id, platform=platform)
            sock_path = str(bundle_path / "run" / "sandbox" / "tool.sock")
            is_alive = await self._wait_for_uds(sock_path=sock_path, proc=proc)
            if is_alive:
                self._resolved_platform = platform
                logger.info(
                    "Platform '%s' booted successfully for %s", platform, tool_key,
                    extra={
                        "tool_key": tool_key, "container_id": container_id, "step": "platform_attempt_success",
                        "platform": platform, "platform_source": source,
                    },
                )
                return platform, proc
            stderr = await self._discard_failed_container(proc, container_id)
            last_stderr_text = stderr.decode(errors="replace")[:500]
            logger.warning(
                "Platform '%s' failed to boot container for %s",
                platform, tool_key,
                extra={
                    "tool_key": tool_key, "container_id": container_id, "step": "platform_attempt_failed",
                    "platform": platform, "platform_source": source, "stderr": last_stderr_text,
                },
            )

            if index == len(chain) - 1:
                logger.error(
                    "All sandbox platforms exhausted for %s (tried: %s) — boot aborted",
                    tool_key, ", ".join(chain),
                    extra={
                        "tool_key": tool_key, "container_id": container_id, "step": "boot_aborted_chain_exhausted",
                        "platforms_tried": list(chain),
                    },
                )
                raise RuntimeError(
                    f"Sandbox container for {tool_key} failed to boot on every platform tried "
                    f"({', '.join(chain)}). Last stderr: {last_stderr_text}"
                )

            next_platform = chain[index + 1]
            logger.error(
                "Sandbox platform '%s' failed to boot container for %s — falling back to '%s'. "
                "Isolation for this process is now running on the fallback platform; investigate "
                "why '%s' failed before relying on it again. stderr: %s",
                platform, tool_key, next_platform, platform, last_stderr_text,
                extra={
                    "tool_key": tool_key, "container_id": container_id, "step": "platform_fallback_triggered",
                    "failed_platform": platform, "fallback_platform": next_platform, "stderr": last_stderr_text,
                },
            )

        # Unreachable — the loop above always returns on success or raises on
        # the last chain element's failure.
        raise RuntimeError(f"Sandbox container for {tool_key} failed to boot (no platforms attempted).")

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

    # Removed _port_alive

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
