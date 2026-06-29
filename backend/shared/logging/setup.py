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

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
