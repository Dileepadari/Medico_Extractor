"""Logging setup.

Two deliberate choices here:

* **JSON by default.** Production logs are consumed by machines; `LOG_FORMAT=console`
  gives a readable line format for local work.
* **No document content is ever logged.** This service handles PHI. Loggers record
  file *metadata* (size, declared type, page-agnostic identifiers) and never the
  bytes, the model prompt, or the extracted field values.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from typing import Any

# Correlates every log line emitted while handling one HTTP request.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"asctime", "message", "taskName"}


class JsonFormatter(logging.Formatter):
    """Minimal structured formatter - no third-party logging dependency."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id

        # Anything passed via `logger.info(..., extra={...})` rides along.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-friendly single-line format for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        request_id = request_id_var.get()
        return f"{line} [req={request_id}]" if request_id else line


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Install a single stdout handler on the root logger (idempotent)."""
    formatter: logging.Formatter = (
        JsonFormatter() if fmt == "json" else ConsoleFormatter()
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn installs its own handlers; route them through ours instead so every
    # line comes out in the same format.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # RequestContextMiddleware already logs every request with the request id,
    # duration and client IP, so uvicorn's own access log is pure duplication.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True

    # These are chatty at INFO and say nothing useful about our own behaviour.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
