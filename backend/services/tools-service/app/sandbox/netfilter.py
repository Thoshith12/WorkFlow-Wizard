"""
app.sandbox.netfilter — iptables management for sandbox network isolation.

Applies and removes iptables rules to block sandbox containers from
reaching internal network addresses. Same CIDR list as the SSRF guard
in http_request.py — consistent policy across both execution paths.

Network mode: gVisor containers run with --network=host, meaning sandbox
traffic originates directly from the host network namespace. This means:
  - FORWARD chain: covers traffic *routed through* the host (Docker bridge
    inter-container traffic). Sandbox host-namespace traffic does NOT go
    through FORWARD — it goes through OUTPUT.
  - OUTPUT chain: covers traffic originated by processes on the host (which
    includes the sandbox running in host-ns). This is the correct chain.

Rule scoping: Each rule carries a unique --comment (tool-sandbox-<id>) so
exact-match deletion finds only the target rule without line-number races.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Same blocked CIDRs as _BLOCKED_NETS in http_request.py
_BLOCKED_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
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

    Rules are tagged with --comment for exact-match deletion later.
    """
    comment = f"tool-sandbox-{container_id}"

    for cidr in _BLOCKED_CIDRS:
        await _run_iptables(
            "-A", "OUTPUT",
            "-d", cidr,
            "-m", "comment", "--comment", comment,
            "-j", "DROP",
        )

    logger.info("Applied iptables OUTPUT rules for container %s (%d CIDRs blocked).", container_id, len(_BLOCKED_CIDRS))


async def remove_iptables_rules(container_id: str) -> None:
    """
    Remove OUTPUT DROP rules for the given container.

    Uses EXACT MATCH deletion (-D with the same args as -A) — NOT line-number
    deletion, which can accidentally remove the wrong rule if rules shift.
    """
    comment = f"tool-sandbox-{container_id}"

    for cidr in _BLOCKED_CIDRS:
        # Exact match: same args as apply, but -D instead of -A
        await _run_iptables(
            "-D", "OUTPUT",
            "-d", cidr,
            "-m", "comment", "--comment", comment,
            "-j", "DROP",
        )

    logger.info("Removed iptables OUTPUT rules for container %s.", container_id)
