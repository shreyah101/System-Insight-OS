"""IST presentation conversions; persisted telemetry always remains UTC."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")
TIME_FIELDS = {"timestamp", "started_at", "ended_at", "requested_at", "trained_at", "resolved_at",
               "first_seen", "last_seen", "heartbeat", "boot_time", "first_sample", "last_sample", "start", "end"}


def as_ist(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Display timestamps must be timezone-aware")
    return parsed.astimezone(IST)


def format_time(value: str | datetime | None, *, time_only: bool = False) -> str:
    if not value:
        return "Unavailable"
    return as_ist(value).strftime("%H:%M:%S IST" if time_only else "%Y-%m-%d %H:%M:%S IST")


def chart_time(value: str | datetime) -> str:
    # Plotly's date axis displays wall times. Remove the offset AFTER conversion
    # so neither Plotly nor the browser converts the labels back to UTC.
    return as_ist(value).replace(tzinfo=None).isoformat()


def localize_timestamps(value):
    """Return a converted copy for JSON/CSV presentation, including nested evidence."""
    if isinstance(value, list):
        return [localize_timestamps(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in TIME_FIELDS and isinstance(item, str) and item:
            result[key] = as_ist(item).isoformat()
        elif key.endswith("_json") and isinstance(item, str):
            result[key] = json.dumps(localize_timestamps(json.loads(item)))
        else:
            result[key] = localize_timestamps(item)
    return result
