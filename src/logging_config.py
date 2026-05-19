"""JSON structured logging for GCP Cloud Logging compatibility.

Cloud Run stdout/stderr lines that are valid JSON are ingested as jsonPayload,
making every field addressable in Cloud Logging queries and the jq filter:
  jq '.[] | {timestamp, event: .jsonPayload.event, query: .jsonPayload.normalized_query}'
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict

_SEVERITY: Dict[int, str] = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

# Standard LogRecord attributes — excluded from the extra-fields pass so they
# don't duplicate or shadow the curated top-level keys.
_BUILTIN = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


class _GCPJsonFormatter(logging.Formatter):
    """Emit one JSON object per log record, compatible with GCP Cloud Logging jsonPayload."""

    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {
            "severity": _SEVERITY.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        }
        for key, val in record.__dict__.items():
            if key not in _BUILTIN and not key.startswith("_"):
                entry[key] = val
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with GCP JSON output on stdout.

    Call once at process startup (lifespan). Replaces logging.basicConfig().
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_GCPJsonFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
