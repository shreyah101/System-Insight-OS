import json

import pytest

from src.display_time import chart_time, format_time, localize_timestamps


def test_ist_conversion_handles_next_day():
    timestamp = "2026-10-29T21:32:35+00:00"
    assert format_time(timestamp) == "2026-10-30 03:02:35 IST"
    assert format_time(timestamp, time_only=True) == "03:02:35 IST"
    assert chart_time(timestamp) == "2026-10-30T03:02:35"


def test_nested_evidence_conversion_preserves_source():
    original = {"first_seen": "2026-10-29T21:32:35+00:00", "resolved_at": None,
                "evidence_json": json.dumps({"sample": {"timestamp": "2026-10-29T21:32:35+00:00"}})}
    converted = localize_timestamps([original])[0]
    assert converted["first_seen"] == "2026-10-30T03:02:35+05:30"
    assert json.loads(converted["evidence_json"])["sample"]["timestamp"].endswith("+05:30")
    assert original["first_seen"].endswith("+00:00")
    assert converted["resolved_at"] is None


def test_missing_and_naive_times():
    assert format_time(None) == "Unavailable"
    with pytest.raises(ValueError, match="timezone-aware"):
        format_time("2026-10-30T03:02:35")
