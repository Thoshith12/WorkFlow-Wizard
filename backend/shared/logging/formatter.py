"""
shared.logging.formatter — JsonFormatter for structured log output.

Emits every log record as a single-line JSON object with the fields:
    timestamp   — ISO 8601 UTC timestamp
    level       — Log level name (INFO, ERROR, etc.)
    service     — Service name (set in configure_logging)
    logger      — Logger name (e.g. "app.services.keycloak")
    trace_id    — Request trace ID if set in context (else null)
    message     — The formatted log message
    extra       — Dict of any extra fields passed to the logger
    exc_info    — Exception traceback string (if present)

This format is directly ingestible by OpenSearch/Logstash/Fluent Bit.

Example output:
    {
        "timestamp": "2026-06-27T10:30:00.123Z",
        "level": "ERROR",
        "service": "backend",
        "logger": "app.services.keycloak",
        "trace_id": "abc123",
        "message": "Keycloak connection failed",
        "extra": {"realm": "master", "attempt": 3},
        "exc_info": "Traceback (most recent call last): ..."
    }
"""
import json
import logging
import traceback
from datetime import datetime, timezone


# Thread-local or contextvar for trace_id injection
_TRACE_ID_FIELD = "trace_id"


class JsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects for OpenSearch ingestion.

    Args:
        service_name: Name of the service — injected into every log record.
    """

    def __init__(self, service_name: str = "unknown") -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        # Build the base log object
        log_object = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "trace_id": getattr(record, _TRACE_ID_FIELD, None),
            "message": record.getMessage(),
        }

        # Collect any extra fields (exclude standard LogRecord attributes)
        _standard_attrs = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "message", "module",
            "msecs", "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName", "trace_id",
        }
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _standard_attrs
        }
        if extra:
            log_object["extra"] = extra

        # Attach exception traceback as a string if present
        if record.exc_info:
            log_object["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            log_object["exc_info"] = record.exc_text

        return json.dumps(log_object, default=str, ensure_ascii=False)
