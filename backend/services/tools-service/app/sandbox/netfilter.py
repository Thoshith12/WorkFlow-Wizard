"""
app.sandbox.netfilter — iptables management for sandbox network isolation.

Applies and removes iptables rules to block sandbox containers from
reaching internal network addresses. Same CIDR list as the SSRF guard
in http_request.py — consistent policy across both execution paths.

Network mode: gVisor containers run with --network=host (rootless runsc does
not support --network=sandbox — see https://github.com/google/gvisor/issues/10359 —
so there is no per-container network namespace/veth to scope rules by
interface). This means:
  - FORWARD chain: covers traffic *routed through* the host (Docker bridge
    inter-container traffic). Sandbox host-namespace traffic does NOT go
    through FORWARD — it goes through OUTPUT.
  - OUTPUT chain: covers traffic originated by processes on the host (which
    includes the sandbox running in host-ns). This is the correct chain.

Rule scoping: Because the sandbox shares the host network namespace, an
OUTPUT rule matched only on destination CIDR would block that traffic for
EVERY process on the host, not just the sandbox — including tools-service's
own Postgres/Redis connections if they happen to be on a blocked range (e.g.
the default Docker Compose bridge subnet, which typically falls inside
172.16.0.0/12). Rules are additionally scoped with `-m owner --uid-owner/
--gid-owner` to the sandboxed process's uid/gid (SandboxConfig.sandbox_uid/
sandbox_gid — the same "nobody" identity oci.py runs the container process
as, with no user-namespace remapping, so it is the real uid on host-emitted
packets). This makes the DROP apply only to sandbox-originated egress.

Residual: this scopes egress only. It does not create a network namespace,
so it does not restrict the sandboxed process from binding/listening on a
host port — that would require the veth-backed --network=sandbox mode that
rootless runsc does not currently support (see link above).

Each rule also carries a unique --comment (tool-sandbox-<id>) so exact-match
deletion finds only the target rule without line-number races.
"""
from __future__ import annotations

import asyncio
import logging

from app.config.tool_settings import tool_settings

logger = logging.getLogger(__name__)

# Same blocked CIDRs as _BLOCKED_NETS in http_request.py
_BLOCKED_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    # 127.0.0.0/8 is removed to allow sandbox loopback TCP server to work
    "169.254.0.0/16",
]


async def _run_iptables(*args: str) -> bool:
    """Run an iptables command. Returns True on success."""
    proc = await asyncio.create_subprocess_exec(
        "iptables", *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("iptables command failed: iptables %s — %s", " ".join(args), stderr.decode().strip())
        return False
    return True


def _owner_match_args() -> list[str]:
    """
    -m owner args scoping a rule to the sandboxed process's uid/gid.

    Only oci.py's sandboxed container process runs as this uid/gid (see
    SandboxConfig.sandbox_uid/sandbox_gid, "nobody" by default, no
    user-namespace remapping) — tools-service's own connections run under a
    different uid and are unaffected by the DROP.
    """
    cfg = tool_settings.sandbox
    return [
        "-m", "owner",
        "--uid-owner", str(cfg.sandbox_uid),
        "--gid-owner", str(cfg.sandbox_gid),
    ]


async def apply_iptables_rules(container_id: str) -> None:
    """
    Add OUTPUT DROP rules to block sandbox-originated traffic to internal CIDRs.

    Uses the OUTPUT chain because gVisor runs with --network=host: sandbox
    processes share the host network namespace, so their outbound packets
    originate on the host and traverse OUTPUT, not FORWARD.

    FORWARD would have zero effect on sandbox traffic (it only covers traffic
    *routed through* the host, e.g. Docker bridge inter-container traffic),
    and adding FORWARD DROP rules for 172.16.0.0/12 would collaterally block
    Docker's own inter-service traffic on the default compose bridge.

    Scoped with -m owner to the sandbox uid/gid (see module docstring) so the
    DROP does not also apply to tools-service's own outbound traffic sharing
    the same host network namespace.

    Rules are tagged with --comment for exact-match deletion later.
    """
    comment = f"tool-sandbox-{container_id}"
    owner_args = _owner_match_args()

    for cidr in _BLOCKED_CIDRS:
        await _run_iptables(
            "-A", "OUTPUT",
            "-d", cidr,
            *owner_args,
            "-m", "comment", "--comment", comment,
            "-j", "DROP",
        )

    logger.info("Applied iptables OUTPUT rules for container %s (%d CIDRs blocked).", container_id, len(_BLOCKED_CIDRS))


async def remove_iptables_rules(container_id: str) -> None:
    """
    Remove OUTPUT DROP rules for the given container.

    Uses EXACT MATCH deletion (-D with the same args as -A, including the
    owner match) — NOT line-number deletion, which can accidentally remove
    the wrong rule if rules shift.
    """
    comment = f"tool-sandbox-{container_id}"
    owner_args = _owner_match_args()

    for cidr in _BLOCKED_CIDRS:
        # Exact match: same args as apply, but -D instead of -A
        await _run_iptables(
            "-D", "OUTPUT",
            "-d", cidr,
            *owner_args,
            "-m", "comment", "--comment", comment,
            "-j", "DROP",
        )

    logger.info("Removed iptables OUTPUT rules for container %s.", container_id)
