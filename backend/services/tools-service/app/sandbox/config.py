"""
app.sandbox.config — Sandbox configuration dataclass.

Re-exports from app.config.tool_settings for convenience within the
sandbox subsystem.
"""
from app.config.tool_settings import SandboxConfig, tool_settings

__all__ = ["SandboxConfig", "tool_settings"]
