from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from src.models import METRICS

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    sampling_interval_seconds: float = 2
    rolling_window_size: int = 60
    zscore_threshold: float = 3
    zscore_medium_threshold: float = 4
    isolation_forest_estimators: int = 100
    isolation_forest_contamination: str | float = "auto"
    random_seed: int = 42
    retraining_interval_samples: int = 30
    recovery_samples_before_retraining: int = 60
    database_path: str = "data/system_insight.sqlite3"
    retention: str = "preserve_all"
    ui_refresh_seconds: float = 2
    stale_after_seconds: float = 10
    feature_change_samples: int = 5
    incident_recovery_samples: int = 5
    minimum_std: dict[str, float] = field(default_factory=lambda: dict(zip(METRICS, (1, .1, 4096, 4096, 1, .1))))
    demo_max_seconds: int = 20
    demo_memory_mb: int = 64
    demo_disk_mb: int = 8
    demo_process_count: int = 3
    demo_cpu_duty: float = .25

    def __post_init__(self):
        positive = ("sampling_interval_seconds", "rolling_window_size", "zscore_threshold", "zscore_medium_threshold", "isolation_forest_estimators", "retraining_interval_samples", "recovery_samples_before_retraining", "ui_refresh_seconds", "stale_after_seconds", "feature_change_samples", "incident_recovery_samples", "demo_max_seconds", "demo_memory_mb", "demo_disk_mb", "demo_process_count")
        for key in positive:
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be a finite positive number")
        for key in ("rolling_window_size", "isolation_forest_estimators", "retraining_interval_samples", "recovery_samples_before_retraining", "feature_change_samples", "incident_recovery_samples", "demo_max_seconds", "demo_memory_mb", "demo_disk_mb", "demo_process_count", "random_seed"):
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key} must be an integer")
        if not 0 <= self.random_seed <= 2**32 - 1:
            raise ValueError("random_seed must be an integer in [0, 2**32 - 1]")
        if self.rolling_window_size < 2:
            raise ValueError("rolling_window_size must be at least 2")
        if self.zscore_medium_threshold <= self.zscore_threshold:
            raise ValueError("zscore_medium_threshold must exceed zscore_threshold")
        contamination = self.isolation_forest_contamination
        if contamination != "auto" and (isinstance(contamination, bool) or not isinstance(contamination, (int, float)) or not 0 < contamination <= .5):
            raise ValueError("isolation_forest_contamination must be auto or in (0, 0.5]")
        if not isinstance(self.minimum_std, dict) or set(self.minimum_std) != set(METRICS) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in self.minimum_std.values()):
            raise ValueError("minimum_std must specify a positive finite floor for each of the six metrics")
        if self.retention != "preserve_all":
            raise ValueError("Only explicit preserve_all retention is supported; history is never automatically deleted")
        if not isinstance(self.database_path, str) or not self.database_path.strip():
            raise ValueError("database_path must be a nonempty path")
        if self.stale_after_seconds < self.sampling_interval_seconds * 2:
            raise ValueError("stale_after_seconds must allow at least two sampling intervals")
        if isinstance(self.demo_cpu_duty, bool) or not isinstance(self.demo_cpu_duty, (int, float)) or not 0 < self.demo_cpu_duty <= .5 or self.demo_max_seconds > 60 or self.demo_memory_mb > 128 or self.demo_disk_mb > 16 or self.demo_process_count > 4:
            raise ValueError("Demo limits exceed conservative caps (60 s, 128 MiB, 16 MiB, 4 children, 50% of one core)")

    @property
    def db_path(self) -> Path:
        p = Path(self.database_path).expanduser()
        return p.resolve() if p.is_absolute() else (ROOT / p).resolve()


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else ROOT / "config.yaml"
    with path.open(encoding="utf-8") as f:
        values = yaml.safe_load(f)
    if not isinstance(values, dict):
        raise ValueError("Configuration must be a YAML mapping")
    unknown = set(values) - {f.name for f in fields(Config)}
    if unknown:
        raise ValueError(f"Unknown configuration fields: {sorted(unknown)}")
    return Config(**values)
