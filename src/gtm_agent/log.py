"""Structured logging via structlog (JSON to stderr)."""

from __future__ import annotations

import logging
import os

import structlog


def configure_logging(level: str | None = None) -> None:
    """Configure structlog once. Safe to call at startup."""
    log_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    numeric = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(format="%(message)s", level=numeric)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger."""
    return structlog.get_logger(name)
