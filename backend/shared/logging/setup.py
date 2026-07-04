"""
shared.logging.setup — Root logger configuration for all services.

Call configure_logging() once at application startup (in main.py or lifespan)
to set up structured JSON logging across the entire service.

Usage:
    from shared.logging.setup import configure_logging
    configure_logging(service_name="backend", level="INFO")
"""
import logging
import sys

from shared.logging.formatter import JsonFormatter


def configure_logging(
    service_name: str = "backend",
    level: str = "INFO",
    json_output: bool = True,
) -> None:
    """
    Configure the root logger for structured JSON output.

    Args:
        service_name: Injected into every log record as "service" field.
        level:        Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output:  If True, use JsonFormatter. If False, use plain text (dev mode).
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate output
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if json_output:
        handler.setFormatter(JsonFormatter(service_name=service_name))
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

    root_logger.addHandler(handler)

    # ── Silence / deduplicate noisy third-party loggers ───────────────────────
    # uvicorn.access: only log WARNING+ (suppress per-request access lines)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # sqlalchemy.engine: SQLAlchemy registers its own plaintext StreamHandler
    # internally if echo=True is used, causing statements to appear twice.
    # Fix: we set echo=False on the engine and manage the logging level here.
    # We clear its own handlers and propagate statements to the root logger
    # so they are formatted cleanly as JSON objects in development.
    _sa_logger = logging.getLogger("sqlalchemy.engine")
    _sa_logger.handlers.clear()
    if level.upper() in ("DEBUG", "INFO"):
        _sa_logger.setLevel(logging.INFO)
    else:
        _sa_logger.setLevel(logging.WARNING)
    _sa_logger.propagate = True   # Propagate to root to output as JSON
