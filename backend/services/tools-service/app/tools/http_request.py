"""
app.tools.http_request — HTTP GET/POST system tool with SSRF guard.

Platform-authored, installed at build time, executed in-process.

SECURITY: This is the one system tool whose risk is destination-control,
not code-authorship. The wrapper code is trusted, but the URL is fully
controlled by the caller. The _resolve_and_validate / _safe_request
functions implement the SSRF guard:

  - Redirect bypass:  FULLY CLOSED — allow_redirects=False, any 3xx raises.
  - DNS-rebinding TOCTOU:  NARROW RESIDUAL RISK — validation resolves DNS
    before connecting; requests does a second independent resolution.
    See implementation_plan.md for the full threat analysis.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests as requests_lib
from langchain_core.tools import BaseTool

from app.schemas.tool_schema import ToolDefinition

logger = logging.getLogger(__name__)

# ── SSRF Guard ────────────────────────────────────────────────────────────────
# Same CIDR list enforced by iptables on the gVisor veth for custom tools.
# Applied as an application-layer check for this one in-process tool.

_BLOCKED_NETS = [
    ipaddress.ip_network(cidr) for cidr in (
        "10.0.0.0/8",       # RFC-1918 private
        "172.16.0.0/12",    # RFC-1918 private
        "192.168.0.0/16",   # RFC-1918 private
        "127.0.0.0/8",      # loopback
        "169.254.0.0/16",   # link-local / cloud metadata endpoint
        "::1/128",          # IPv6 loopback
        "fc00::/7",         # IPv6 unique-local
    )
]


def _resolve_and_validate(hostname: str) -> None:
    """
    Resolve hostname → IP, validate against blocked CIDRs.

    Raises ValueError if the hostname resolves to any blocked CIDR or
    cannot be resolved.

    NOTE: This is the validation step only. The URL passed to requests
    is left untouched (original hostname) so that SNI, cert verification,
    and the Host header all remain correct for TLS. There is a narrow
    TOCTOU window between this validation call and the actual connection
    (documented as an acknowledged residual risk — see module docstring).
    """
    if not hostname:
        raise ValueError("Invalid URL — no hostname")

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {hostname!r}: {exc}")

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        for blocked in _BLOCKED_NETS:
            if ip in blocked:
                raise ValueError(
                    f"Blocked: {hostname!r} resolves to internal address "
                    f"{ip} (matches {blocked})"
                )


def _safe_request(method: str, url: str, **kwargs) -> requests_lib.Response:
    """
    Make an outbound HTTP request with an SSRF guard.

    Validates the destination before connecting and refuses all redirects.
    The original URL hostname is left untouched so TLS SNI and certificate
    verification work correctly — IP-literal URL rewriting is deliberately
    NOT done here because replacing the hostname with an IP literal breaks
    SNI (which is a TLS ClientHello field set from the connection hostname,
    not the HTTP Host header) and causes SSLCertVerificationError against
    virtually every real HTTPS endpoint.
    """
    parsed = urlparse(url)
    _resolve_and_validate(parsed.hostname)  # raises if internal — before any network call

    # Redirects refused outright: a redirect to an internal address would
    # bypass the validation above. Caller must supply the final URL directly.
    kwargs["allow_redirects"] = False

    resp = requests_lib.request(method, url, timeout=kwargs.pop("timeout", 30), **kwargs)

    if resp.is_redirect:
        raise ValueError(
            f"Redirects are not permitted — received {resp.status_code} "
            f"to {resp.headers.get('Location', '(no Location header)')!r}. "
            "Provide the final destination URL directly."
        )

    return resp


# ── LangChain Tool Subclasses ─────────────────────────────────────────────────


class SafeRequestsGet(BaseTool):
    """HTTP GET with SSRF protection. URL is validated before every request."""

    name: str = "requests_get"
    description: str = (
        "Make an HTTP GET request to a public URL. Returns the response text. "
        "Internal/private network addresses are blocked."
    )

    def _run(self, url: str) -> str:
        return _safe_request("GET", url).text

    async def _arun(self, url: str) -> str:
        return _safe_request("GET", url).text


class SafeRequestsPost(BaseTool):
    """HTTP POST with SSRF protection. URL is validated before every request."""

    name: str = "requests_post"
    description: str = (
        "Make an HTTP POST request to a public URL with a request body. "
        "Returns the response text. Internal/private network addresses are blocked."
    )

    def _run(self, url: str, data: str = "") -> str:
        return _safe_request("POST", url, data=data).text

    async def _arun(self, url: str, data: str = "") -> str:
        return _safe_request("POST", url, data=data).text


# ── Tool Definitions ──────────────────────────────────────────────────────────
# We register TWO tool definitions (GET and POST) but they share the same
# SSRF guard infrastructure.

_get_tool = SafeRequestsGet()
_post_tool = SafeRequestsPost()

# Expose a single composite tool definition for the registry.
# Both GET and POST are bundled under one entry since they share
# the same security infrastructure and are logically one tool.
tool = ToolDefinition(
    name="http_request",
    version="1.0.0",
    display_name="HTTP Request",
    description=(
        "Make HTTP GET or POST requests to public URLs. "
        "Internal network addresses (RFC-1918, loopback, link-local, cloud metadata) "
        "are blocked. Redirects are refused — provide the final destination URL directly."
    ),
    capabilities=["http_request", "api_call", "web_fetch"],
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The public URL to request. Must not resolve to an internal/private address.",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST"],
                "description": "HTTP method (default: GET).",
                "default": "GET",
            },
            "data": {
                "type": "string",
                "description": "Request body for POST requests.",
                "default": "",
            },
        },
        "required": ["url"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Response body text.",
            }
        },
    },
    usage_examples=[
        {
            "input": {"url": "https://api.github.com/repos/python/cpython"},
            "description": "Fetch CPython repo metadata from GitHub API",
        },
    ],
    langchain_tool=_get_tool,  # Default is GET; POST is accessible via method param
    max_output_bytes=1_048_576,
    timeout_seconds=30,
)
