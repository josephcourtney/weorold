from __future__ import annotations

from datetime import datetime


def validate_time_window(start: datetime, end: datetime) -> None:
    """Validate the timezone-aware half-open time window used by remote sources."""

    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start must be timezone-aware")
    if end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("end must be timezone-aware")
    if end <= start:
        raise ValueError("end must be after start")
