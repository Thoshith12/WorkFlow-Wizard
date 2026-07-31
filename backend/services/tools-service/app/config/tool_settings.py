"""
app.config.tool_settings — Tools service + sandbox configuration.

Defines ToolSettings (service-level) and SandboxConfig (frozen dataclass
for all gVisor sandbox knobs). Both read from environment variables.

Usage:
    from app.config.tool_settings import tool_settings
    print(tool_settings.sandbox.memory_mb)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Tuple

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_Platform = Literal["ptrace", "systrap", "kvm"]


@dataclass(frozen=True)
class SandboxConfig:
    """
    Immutable configuration for the gVisor sandbox subsystem.

    All values map 1:1 to SANDBOX_* environment variables (uppercased).
    """

    mode: Literal["none", "gvisor"] = "gvisor"
    # Total host RAM budget per sandbox (runsc RSS), including systrap/sentry.
    # Sized for ~10 parallel tools on a 4 GB microservice (4000 / 10 ≈ 400).
    memory_mb: int = 400
    # gVisor systrap/sentry + Python baseline — subtracted from memory_mb for
    # the in-guest RSS cap so tool code cannot spend the whole budget.
    runtime_overhead_mb: int = 64
    # Virtual address space (RLIMIT_AS). Larger than memory_mb so ML libs can
    # mmap model files without committing that much physical RAM.
    virtual_memory_mb: int = 2048
    pids_limit: int = 16
    cpu_quota_percent: int = 300  # 300% = 3 cores max

    # Sandboxed process identity — single source of truth shared by oci.py
    # (container process uid/gid) and netfilter.py (iptables -m owner scoping).
    sandbox_uid: int = 65534  # nobody
    sandbox_gid: int = 65534  # nobody

    # gVisor syscall-interception platform. Preferred is attempted first on a
    # container's first boot in this process; if it fails, pool.py walks
    # platform_fallback_chain in order and stays on whatever worked for the
    # rest of the process's lifetime. Set allow_platform_fallback=False to have
    # boot fail hard on the first failure instead of walking the chain.
    platform_preferred: _Platform = "kvm"
    platform_fallback_chain: Tuple[_Platform, ...] = ("systrap", "ptrace")
    allow_platform_fallback: bool = True

    # Dev-only escape hatch for gVisor's sentry/gofer bootstrap (its own mount
    # namespace + chroot + /proc mount) failing when runsc itself runs nested
    # inside another container's already-restricted mount namespace — appends
    # --TESTONLY-unsafe-nonroot, which reuses the host's existing /proc and /
    # instead of creating a new mount namespace for the gofer. Named exactly
    # that way by gVisor's own maintainers — NOT a substitute for a real target
    # environment, and must never be set outside local dev. Does not weaken the
    # isolation between the sandboxed application and the sentry (ptrace/
    # systrap/kvm syscall interception, and the uid-owner iptables scoping, are
    # both unaffected) — only the sentry/gofer's own isolation from the host.
    unsafe_nested_dev: bool = False

    # Per-subprocess execution timeout — kills the subprocess ONLY, not the container.
    exec_timeout_seconds: int = 30

    # Queue control
    queue_timeout_seconds: int = 15       # patience waiting for semaphore slot
    max_inflight: int = 10                # simultaneous subprocess slots per container
    max_queued: int = 20                  # coroutines waiting before SandboxBusy

    # Executor-level capacity
    max_concurrent_global: int = 50
    max_concurrent_per_tool: int = 15

    # Container lifecycle — per-container, NOT per-request.
    idle_timeout_seconds: int = 1000      # 1000s idle → reap
    max_lifetime_seconds: int = 21600     # 6h → force recycle
    max_requests_per_container: int = 5000

    # Misc
    max_output_bytes: int = 1_048_576     # 1 MB
    venv_cache_size: int = 50
    reaper_interval_seconds: int = 60
    tmpfs_size_mb: int = 10
    max_requirements: int = 20


class ToolSettings(BaseSettings):
    """
    Tools service settings — read from environment variables.

    Includes a nested SandboxConfig built from SANDBOX_* env vars.
    """

    # ── Sandbox ──────────────────────────────────────────────────────────────
    SANDBOX_MODE: Literal["none", "gvisor"] = Field(default="gvisor")
    SANDBOX_MEMORY_MB: int = Field(default=400)
    SANDBOX_RUNTIME_OVERHEAD_MB: int = Field(default=64)
    SANDBOX_VIRTUAL_MEMORY_MB: int = Field(default=2048)
    SANDBOX_PIDS_LIMIT: int = Field(default=16)
    SANDBOX_CPU_QUOTA_PERCENT: int = Field(default=300)
    SANDBOX_UID: int = Field(default=65534)
    SANDBOX_GID: int = Field(default=65534)
    SANDBOX_PLATFORM_PREFERRED: _Platform = Field(default="kvm")
    SANDBOX_PLATFORM_FALLBACK_CHAIN: str = Field(default="systrap,ptrace")
    SANDBOX_ALLOW_PLATFORM_FALLBACK: bool = Field(default=True)
    SANDBOX_UNSAFE_NESTED_DEV: bool = Field(default=False)
    SANDBOX_EXEC_TIMEOUT_SECONDS: int = Field(default=30)
    SANDBOX_QUEUE_TIMEOUT_SECONDS: int = Field(default=15)
    SANDBOX_MAX_INFLIGHT: int = Field(default=10)
    SANDBOX_MAX_QUEUED: int = Field(default=20)
    SANDBOX_MAX_CONCURRENT_GLOBAL: int = Field(default=50)
    SANDBOX_MAX_CONCURRENT_PER_TOOL: int = Field(default=15)
    SANDBOX_IDLE_TIMEOUT_SECONDS: int = Field(default=1000)
    SANDBOX_MAX_LIFETIME_SECONDS: int = Field(default=21600)
    SANDBOX_MAX_REQUESTS_PER_CONTAINER: int = Field(default=5000)
    SANDBOX_MAX_OUTPUT_BYTES: int = Field(default=1_048_576)
    SANDBOX_VENV_CACHE_SIZE: int = Field(default=50)
    SANDBOX_REAPER_INTERVAL_SECONDS: int = Field(default=60)
    SANDBOX_TMPFS_SIZE_MB: int = Field(default=10)
    SANDBOX_MAX_REQUIREMENTS: int = Field(default=20)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sandbox(self) -> SandboxConfig:
        """Build a frozen SandboxConfig from the flat SANDBOX_* env vars."""
        return SandboxConfig(
            mode=self.SANDBOX_MODE,
            memory_mb=self.SANDBOX_MEMORY_MB,
            runtime_overhead_mb=self.SANDBOX_RUNTIME_OVERHEAD_MB,
            virtual_memory_mb=self.SANDBOX_VIRTUAL_MEMORY_MB,
            pids_limit=self.SANDBOX_PIDS_LIMIT,
            cpu_quota_percent=self.SANDBOX_CPU_QUOTA_PERCENT,
            sandbox_uid=self.SANDBOX_UID,
            sandbox_gid=self.SANDBOX_GID,
            platform_preferred=self.SANDBOX_PLATFORM_PREFERRED,
            platform_fallback_chain=tuple(
                p.strip() for p in self.SANDBOX_PLATFORM_FALLBACK_CHAIN.split(",") if p.strip()
            ),
            allow_platform_fallback=self.SANDBOX_ALLOW_PLATFORM_FALLBACK,
            unsafe_nested_dev=self.SANDBOX_UNSAFE_NESTED_DEV,
            exec_timeout_seconds=self.SANDBOX_EXEC_TIMEOUT_SECONDS,
            queue_timeout_seconds=self.SANDBOX_QUEUE_TIMEOUT_SECONDS,
            max_inflight=self.SANDBOX_MAX_INFLIGHT,
            max_queued=self.SANDBOX_MAX_QUEUED,
            max_concurrent_global=self.SANDBOX_MAX_CONCURRENT_GLOBAL,
            max_concurrent_per_tool=self.SANDBOX_MAX_CONCURRENT_PER_TOOL,
            idle_timeout_seconds=self.SANDBOX_IDLE_TIMEOUT_SECONDS,
            max_lifetime_seconds=self.SANDBOX_MAX_LIFETIME_SECONDS,
            max_requests_per_container=self.SANDBOX_MAX_REQUESTS_PER_CONTAINER,
            max_output_bytes=self.SANDBOX_MAX_OUTPUT_BYTES,
            venv_cache_size=self.SANDBOX_VENV_CACHE_SIZE,
            reaper_interval_seconds=self.SANDBOX_REAPER_INTERVAL_SECONDS,
            tmpfs_size_mb=self.SANDBOX_TMPFS_SIZE_MB,
            max_requirements=self.SANDBOX_MAX_REQUIREMENTS,
        )


tool_settings = ToolSettings()
