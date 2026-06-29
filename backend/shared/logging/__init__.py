"""
shared.logging — Structured JSON logging for OpenSearch compatibility.

Provides a JsonFormatter and configure_logging() setup function
that emits all log records as JSON objects, directly ingestible
by OpenSearch, Logstash, or Fluent Bit without transformation.

Usage:
    from shared.logging.setup import configure_logging
    configure_logging(service_name="backend", level="INFO")
"""
