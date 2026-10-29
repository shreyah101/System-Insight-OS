"""Chronological replay and honest, sample-level and interval-level evaluation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np

from src.config import Config
from src.detection import DetectionEngine
from src.models import METRICS, Sample, Severity

SCENARIOS = ("Stable normal", "CPU spike", "Memory growth", "Disk I/O spike", "Process increase", "Multivariate outlier")


def scenario_samples(name: str, config: Config, seed: int = 42) -> tuple[list[Sample], list[bool]]:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario {name}")
    rng = np.random.default_rng(seed)
    warm = config.rolling_window_size + 20
    count = warm + 30 + 80
    centers = np.array([25., 45., 20000., 15000., 140., 2.])
    noise = np.array([2., .4, 2500., 2000., 2., .2])
    matrix = rng.normal(centers, noise, size=(count, 6))
    labels = [False] * count
    onset, end = warm, warm + 30
    if name != "Stable normal":
        labels[onset:end] = [True] * (end - onset)
    if name == "CPU spike":
        matrix[onset:end, 0] += 55
    elif name == "Memory growth":
        matrix[onset:end, 1] += np.linspace(0, 35, end - onset)
    elif name == "Disk I/O spike":
        matrix[onset:end, 2:4] += 2_000_000
    elif name == "Process increase":
        matrix[onset:end, 4] += 100
    elif name == "Multivariate outlier":
        matrix[onset:end] += np.array([30, 18, 40000, 40000, 45, 10])
    matrix = np.maximum(matrix, 0)
    matrix[:, [0, 1, 5]] = np.minimum(matrix[:, [0, 1, 5]], 100)
    matrix[:, 4] = np.round(matrix[:, 4])
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Sample(start + timedelta(seconds=i * config.sampling_interval_seconds), dict(zip(METRICS, row.tolist()))) for i, row in enumerate(matrix)], labels


def classification_metrics(truth: list[bool], predicted: list[bool]) -> dict:
    if len(truth) != len(predicted):
        raise ValueError("Truth and prediction lengths differ")
    tp = sum(t and p for t, p in zip(truth, predicted))
    fp = sum(not t and p for t, p in zip(truth, predicted))
    fn = sum(t and not p for t, p in zip(truth, predicted))
    tn = sum(not t and not p for t, p in zip(truth, predicted))
    precision = tp / (tp + fp) if tp + fp else 0.
    recall = tp / (tp + fn) if tp + fn else 0.
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.}


def interval_metrics(rows: list[dict], intervals: list[dict], recovery_samples: int | None = None) -> dict:
    recovery_samples = recovery_samples or Config().incident_recovery_samples
    eligible = [r for r in rows if r["ready"]]
    results = []
    for interval in intervals:
        start, end = datetime.fromisoformat(interval["start"]), datetime.fromisoformat(interval["end"])
        observed = [r for r in eligible if start <= datetime.fromisoformat(r["timestamp"]) <= end]
        hits = [r for r in observed if r["severity"] != "NORMAL"]
        first = min((datetime.fromisoformat(r["timestamp"]) for r in hits), default=None)
        following = sorted((r for r in rows if datetime.fromisoformat(r["timestamp"]) > end), key=lambda r: r["timestamp"])
        # Recovery means the configured run of consecutive unflagged eligible readings.
        recovery = None
        for i in range(len(following) - recovery_samples + 1):
            if all(r["ready"] and r["severity"] == "NORMAL" for r in following[i:i + recovery_samples]):
                recovery = (datetime.fromisoformat(following[i + recovery_samples - 1]["timestamp"]) - end).total_seconds()
                break
        results.append({"scenario": interval.get("scenario", "workload"), "eligible_samples": len(observed), "detections": len(hits),
                        "missed": not bool(hits), "latency_seconds": (first - start).total_seconds() if first else None,
                        "recovery_seconds": recovery, "recovery_samples_required": recovery_samples})
    return {"intervals": results, "missed_intervals": sum(r["missed"] for r in results)}


def replay(name: str, config: Config) -> tuple[list[dict], dict]:
    samples, labels = scenario_samples(name, config, config.random_seed)
    engine = DetectionEngine(config)
    rows, truth, zflags, fflags, combined = [], [], [], [], []
    for sample, label in zip(samples, labels):
        result = engine.step(sample)
        rows.append({"timestamp": sample.timestamp.isoformat(), **sample.values, "ready": result.ready,
                     "severity": result.severity.value, "z_flag": result.zscore.anomaly, "forest_flag": result.forest.anomaly,
                     "forest_score": result.forest.score, "simulated_workload": label, "decision_json": json.dumps(result.to_dict())})
        if result.ready:
            truth.append(label)
            zflags.append(result.zscore.anomaly)
            fflags.append(result.forest.anomaly)
            combined.append(result.severity != Severity.NORMAL)
    report = {"source": "synthetic", "scenario": name, "seed": config.random_seed, "samples": len(samples), "eligible_samples": len(truth),
              "zscore": classification_metrics(truth, zflags), "isolation_forest": classification_metrics(truth, fflags),
              "combined": classification_metrics(truth, combined)}
    if any(labels):
        indices = [i for i, flag in enumerate(labels) if flag]
        report.update(interval_metrics(rows, [{"scenario": name, "start": samples[indices[0]].timestamp.isoformat(), "end": samples[indices[-1]].timestamp.isoformat()}], config.incident_recovery_samples))
    return rows, report


def evaluate_local(repository, session_id: str) -> dict:
    session = repository.session(session_id)
    if not session or session["source"] != "live":
        raise ValueError("Select an existing live session")
    # A deliberate evaluation reads the session once; dashboard refreshes never use this.
    with repository.connection() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM metrics_history WHERE session_id=? ORDER BY timestamp,id", (session_id,))]
        alerts = [dict(r) for r in conn.execute("SELECT * FROM alerts WHERE session_id=? ORDER BY first_seen", (session_id,))]
    events = repository.workloads(session_id, limit=10000)
    complete = [e for e in events if e["started_at"] and e["ended_at"]]
    intervals = [{"start": e["started_at"], "end": e["ended_at"], "scenario": e["scenario"]} for e in complete]
    settings = json.loads(session["config_json"])
    recovery_samples = settings.get("incident_recovery_samples", Config().incident_recovery_samples)
    result = interval_metrics(rows, intervals, recovery_samples)
    eligible = [r for r in rows if r["ready"]]
    truth = [any(i["start"] <= r["timestamp"] <= i["end"] for i in intervals) for r in eligible]
    timings = [json.loads(r["decision_json"])["timing"] for r in rows]
    result.update({"source": "live", "session_id": session_id, "samples": len(rows), "eligible_samples": len(eligible),
                   "recorded_duration_seconds": (datetime.fromisoformat(rows[-1]["timestamp"]) - datetime.fromisoformat(rows[0]["timestamp"])).total_seconds() if len(rows) > 1 else 0,
                   "label_interpretation": "Known workload intervals are not confirmed OS failures; unlabelled activity is only presumed ordinary.",
                   "unfinished_workloads": sum(e["started_at"] is not None and e["ended_at"] is None for e in events),
                   "episodes_starting_outside_recorded_workloads": sum(not any(i["start"] <= a["first_seen"] <= i["end"] for i in intervals) for a in alerts),
                   "zscore": classification_metrics(truth, [bool(r["z_flag"]) for r in eligible]),
                   "isolation_forest": classification_metrics(truth, [bool(r["forest_flag"]) for r in eligible]),
                   "combined": classification_metrics(truth, [r["severity"] != "NORMAL" for r in eligible])})
    result["overhead"] = {key: {"mean": float(np.mean(values)), "max": max(values)} for key in ("detection_ms", "collection_and_detection_ms", "sampling_lateness_ms", "monitor_cpu_percent", "monitor_ram_mib") if (values := [t[key] for t in timings if key in t])}
    return result
