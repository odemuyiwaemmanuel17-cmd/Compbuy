"""Utilities for converting Supabase row payloads into typed Python values."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def as_str(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def as_opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def as_int(value: Any, *, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def as_opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def as_datetime(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp; fall back to "now" for missing/invalid data."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [item for item in (part.strip() for part in value.split(",")) if item]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    return []
