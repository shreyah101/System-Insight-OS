import json
from dataclasses import replace

import pytest

from src.evaluation import SCENARIOS, classification_metrics, evaluate_local, interval_metrics, replay
from src.models import utc_now
from src.storage import Repository
from src.workloads import execute, limits


def test_confusion_matrix_and_metrics():
    report = classification_metrics([True, True, False, False], [True, False, True, False])
    assert report == {"tp": 1, "fp": 1, "fn": 1, "tn": 1, "precision": .5, "recall": .5, "f1": .5}
    assert classification_metrics([], [])["f1"] == 0
    with pytest.raises(ValueError):
        classification_metrics([True], [])


def test_latency_and_missed_intervals():
    rows = [{"timestamp": f"2026-01-01T00:00:{second:02d}+00:00", "ready": second != 0, "severity": "LOW" if second == 4 else "NORMAL"} for second in range(12)]
    result = interval_metrics(rows, [{"start": "2026-01-01T00:00:02+00:00", "end": "2026-01-01T00:00:06+00:00"}, {"start": "2026-01-01T00:01:00+00:00", "end": "2026-01-01T00:02:00+00:00"}])
    assert result["intervals"][0]["latency_seconds"] == 2
    assert result["intervals"][1]["latency_seconds"] is None
    assert result["intervals"][0]["recovery_seconds"] == 5
    assert result["missed_intervals"] == 1


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_real_engine_synthetic_replay(config, scenario):
    rows, report = replay(scenario, config)
    assert report["source"] == "synthetic"
    assert report["eligible_samples"] == len(rows) - config.rolling_window_size
    assert all(not r["ready"] for r in rows[:config.rolling_window_size])
    assert all(r["forest_score"] is not None for r in rows[config.rolling_window_size:])
    assert all(r["severity"] == "NORMAL" for r in rows[:config.rolling_window_size])
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("kind", ["CPU activity", "Memory growth", "Disk I/O activity", "Process activity"])
def test_bounded_workload_completion(config, kind):
    repo = Repository(config.db_path)
    repo.initialize()
    session = repo.start_session({}, {})
    cfg = replace(config, demo_max_seconds=1, demo_memory_mb=2, demo_disk_mb=1, demo_process_count=1)
    event_id = repo.create_workload(kind, limits(cfg), session)
    execute(repo, event_id)
    event = repo.workload(event_id)
    assert event["status"] == "completed", event["error"]
    assert event["started_at"] and event["ended_at"]
    report = evaluate_local(repo, session)
    assert report["samples"] == 0
    assert report["missed_intervals"] == 1
    assert report["intervals"][0]["latency_seconds"] is None


def test_workload_cancellation_and_limits(config):
    repo = Repository(config.db_path)
    repo.initialize()
    event_id = repo.create_workload("Memory growth", limits(config), None)
    repo.update_workload(event_id, cancel_requested=1)
    execute(repo, event_id)
    assert repo.workload(event_id)["status"] == "cancelled"
    event_id = repo.create_workload("Memory growth", {**limits(config), "memory_mb": 99999}, None)
    execute(repo, event_id)
    assert repo.workload(event_id)["status"] == "failed"
    assert repo.workload(event_id)["started_at"] is None


def test_local_evaluation_empty_session(config):
    repo = Repository(config.db_path)
    repo.initialize()
    session = repo.start_session({}, {})
    report = evaluate_local(repo, session)
    assert report["samples"] == 0
    assert report["overhead"] == {}
    assert report["recorded_duration_seconds"] == 0


def test_missing_readings_break_recovery_streak():
    rows = [{"timestamp": f"2026-01-01T00:00:{i:02d}+00:00", "ready": i != 3, "severity": "NORMAL"} for i in range(7)]
    report = interval_metrics(rows, [{"start": rows[0]["timestamp"], "end": rows[0]["timestamp"]}], recovery_samples=4)
    assert report["intervals"][0]["recovery_seconds"] is None
