"""
logger.py — JSON-based query audit logging
Writes every query attempt to query_logs.json with full context.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = os.getenv("LOG_PATH", "query_logs.json")


def _load_logs() -> list:
    path = Path(LOG_PATH)
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_logs(logs: list):
    with open(LOG_PATH, "w") as f:
        json.dump(logs, f, indent=2, default=str)


def log_query(
    question: str,
    sql: str | None,
    results_count: int | None,
    success: bool,
    error: str | None = None,
    duration_ms: float | None = None,
):
    """Append one query log entry to query_logs.json."""
    entry = {
        "id":            len(_load_logs()) + 1,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "question":      question,
        "sql":           sql,
        "results_count": results_count,
        "success":       success,
        "error":         error,
        "duration_ms":   round(duration_ms, 2) if duration_ms else None,
    }
    logs = _load_logs()
    logs.append(entry)
    _save_logs(logs)
    return entry


def get_logs(limit: int = 50) -> list:
    """Return the most recent `limit` log entries (newest first)."""
    logs = _load_logs()
    return list(reversed(logs))[:limit]
