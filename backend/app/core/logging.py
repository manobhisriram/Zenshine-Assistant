"""Structured JSON logging with request correlation and PII masking."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){9,14}\d(?!\d)")


def mask_pii(value: str) -> str:
    """Mask e-mail addresses and phone-like numbers before text reaches logs."""
    value = _EMAIL.sub("[email]", value)
    return _PHONE.sub("[phone]", value)


def _redact_processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key, val in list(event_dict.items()):
        if isinstance(val, str) and key not in {"event", "request_id", "timestamp", "level"}:
            event_dict[key] = mask_pii(val)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level, logging.INFO))
    for noisy in ("httpx", "httpcore", "pinecone", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_processor,  # type: ignore[list-item]
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level, logging.INFO)),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
