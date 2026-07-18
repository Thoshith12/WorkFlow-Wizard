"""
app.sandbox.base_executor — Abstract interface for sandbox executors.

Deliberate extension point: allows adding a `none`-mode executor for
development without gVisor available, while the gVisor executor is the
production default. This is NOT copy-paste residue from the other project —
it is a deliberate choice for this project's development workflow.
"""
from __future__ import annotations

import abc
from typing import Any, Dict

from app.models.custom_tool import CustomTool


class BaseSandboxExecutor(abc.ABC):
    """
    Abstract interface for sandbox execution backends.

    All custom tool execution goes through a concrete implementation
    of this interface. The production implementation is GVisorSandboxExecutor.
    """

    @abc.abstractmethod
    async def execute(
        self,
        *,
        tool: CustomTool,
        input_data: Dict[str, Any],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """
        Execute user code inside a sandbox and return the result.

        Args:
            tool:            The CustomTool ORM object with code + config.
            input_data:      Tool input payload.
            timeout_seconds: Per-execution subprocess timeout.

        Returns:
            The tool's output as a dict.

        Raises:
            SandboxBusy:       Queue is full — caller should retry.
            SandboxTimeout:    Execution timed out.
            SandboxError:      Execution failed (code error, crash, etc.).
        """
        ...

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Graceful shutdown — stop all containers, release resources."""
        ...


class SandboxBusy(Exception):
    """Raised when the sandbox queue is full. Caller should return 503 + Retry-After."""
    pass


class SandboxTimeout(Exception):
    """Raised when a sandbox execution exceeds EXEC_TIMEOUT."""
    pass


class SandboxError(Exception):
    """Raised when sandbox execution fails (code error, crash, etc.)."""
    pass
