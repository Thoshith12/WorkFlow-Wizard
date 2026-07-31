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

# DNS is explicitly permitted before the DROP rules so the sandbox can
# resolve external hostnames (HuggingFace, PyPI, etc.).
# Docker's embedded DNS sits at 127.0.0.11 (loopback, already exempt) but
# /etc/resolv.conf may also reference a 172.x.x.x gateway DNS — these ACCEPT
# rules ensure port-53 traffic is never caught by the 172.16.0.0/12 DROP.
_DNS_PROTOCOLS = ["udp", "tcp"]
_DNS_PORT = "53"


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
    Add OUTPUT rules to:
      1. ACCEPT DNS (port 53 UDP+TCP) — allows sandbox to resolve external
         hostnames (HuggingFace, PyPI) even if the nameserver sits in a
         blocked CIDR range (e.g. 172.x Docker gateway DNS).
      2. DROP all other traffic to RFC-1918 internal CIDRs — prevents sandbox
         from reaching internal services (Postgres, Redis, other containers).

    Rules are scoped with -m owner to the sandbox uid/gid so they only affect
    sandbox-originated egress, not tools-service's own connections.
    Rules are tagged with --comment for exact-match deletion later.
    """
    comment = f"tool-sandbox-{container_id}"
    owner_args = _owner_match_args()

    # ── Step 1: ACCEPT DNS before any DROP rules ─────────────────────────────
    for proto in _DNS_PROTOCOLS:
        await _run_iptables(
            "-I", "OUTPUT", "1",  # insert at top so it's evaluated first
            "-p", proto,
            "--dport", _DNS_PORT,
            *owner_args,
            "-m", "comment", "--comment", f"{comment}-dns",
            "-j", "ACCEPT",
        )

    # ── Step 2: DROP RFC-1918 internal CIDRs ────────────────────────────────
    for cidr in _BLOCKED_CIDRS:
        await _run_iptables(
            "-A", "OUTPUT",
            "-d", cidr,
            *owner_args,
            "-m", "comment", "--comment", comment,
            "-j", "DROP",
        )

    logger.info(
        "Applied iptables OUTPUT rules for container %s: DNS ACCEPT + %d CIDRs blocked.",
        container_id, len(_BLOCKED_CIDRS),
    )


async def remove_iptables_rules(container_id: str) -> None:
    """
    Remove OUTPUT rules (DNS ACCEPT + CIDR DROP) for the given container.

    Uses EXACT MATCH deletion (-D with the same args as -A/-I, including the
    owner match) — NOT line-number deletion, which can accidentally remove
    the wrong rule if rules shift.
    """
    comment = f"tool-sandbox-{container_id}"
    owner_args = _owner_match_args()

    # Remove DNS ACCEPT rules
    for proto in _DNS_PROTOCOLS:
        await _run_iptables(
            "-D", "OUTPUT",
            "-p", proto,
            "--dport", _DNS_PORT,
            *owner_args,
            "-m", "comment", "--comment", f"{comment}-dns",
            "-j", "ACCEPT",
        )

    # Remove CIDR DROP rules
    for cidr in _BLOCKED_CIDRS:
        await _run_iptables(
            "-D", "OUTPUT",
            "-d", cidr,
            *owner_args,
            "-m", "comment", "--comment", comment,
            "-j", "DROP",
        )

    logger.info("Removed iptables OUTPUT rules for container %s.", container_id)
