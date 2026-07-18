"""
app.models.enums.tools — Tool-domain enumerations.

Used across ORM models, schemas, and service logic.
"""
from enum import Enum


class ToolType(str, Enum):
    """Discriminator for system vs. custom tools in API responses."""
    SYSTEM = "system"
    CUSTOM = "custom"


class ToolStatus(str, Enum):
    """Lifecycle status of a custom tool registration."""
    ACTIVE = "active"
    INACTIVE = "inactive"


class ExecutionStatus(str, Enum):
    """Outcome status of a tool execution attempt."""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
