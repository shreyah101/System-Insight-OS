from __future__ import annotations

from collections import deque
import time

import numpy as np
from sklearn.ensemble import IsolationForest

from src.config import Config
from src.models import BaselineStat, Decision, ForestResult, LABELS, METRICS, Sample, Severity, ZResult
from src.telemetry import validate_sample


class RollingBaseline:
    def __init__(self, config: Config, features: tuple[str, ...]):
        self.config, self.features = config, features
        self.rows: deque[dict[str, float]] = deque(maxlen=config.rolling_window_size)

    @property
    def ready(self) -> bool:
        return bool(self.features) and len(self.rows) == self.config.rolling_window_size

    def add(self, sample: Sample):
        if self.features and all(sample.values.get(k) is not None for k in self.features):
            self.rows.append({k: sample.values[k] for k in self.features})

    def statistics(self) -> dict[str, BaselineStat]:
        if not self.rows:
            return {}
        result = {}
        for key in self.features:
            array = np.array([r[key] for r in self.rows])
            std = float(array.std(ddof=0))
            result[key] = BaselineStat(float(array.mean()), std, max(std, self.config.minimum_std[key]), len(array))
        return result

    def matrix(self) -> np.ndarray:
        return np.array([[r[k] for k in self.features] for r in self.rows], dtype=float)


class ZScoreDetector:
    def __init__(self, threshold: float = 3):
        self.threshold = threshold

    def detect(self, sample: Sample, baseline: dict[str, BaselineStat]) -> ZResult:
        result = ZResult(baseline=baseline)
        for key, stat in baseline.items():
            value = sample.values.get(key)
            if value is None:
                continue
            z = (value - stat.mean) / stat.effective_std
            result.scores[key], result.observed[key] = float(z), value
            if abs(z) > self.threshold:
                result.flagged.append(key)
        return result


class ForestDetector:
    def __init__(self, config: Config):
        self.config = config
        self.model: IsolationForest | None = None
        self.features: tuple[str, ...] = ()
        self.trained_at = None
        self.training_samples = 0

    def fit(self, baseline: RollingBaseline, timestamp: str):
        if not baseline.ready:
            raise ValueError("A complete historical window is required for fitting")
        model = IsolationForest(n_estimators=self.config.isolation_forest_estimators,
                                contamination=self.config.isolation_forest_contamination,
                                random_state=self.config.random_seed, n_jobs=1)
        model.fit(baseline.matrix())
        self.model, self.features = model, baseline.features
        self.trained_at, self.training_samples = timestamp, len(baseline.rows)

    def detect(self, sample: Sample) -> ForestResult:
        result = ForestResult(features=self.features, trained_at=self.trained_at, training_samples=self.training_samples)
        if self.model is None or any(sample.values.get(k) is None for k in self.features):
            return result
        row = np.array([[sample.values[k] for k in self.features]], dtype=float)
        result.ready = True
        result.score = float(self.model.decision_function(row)[0])
        result.anomaly = bool(self.model.predict(row)[0] == -1)
        return result


def classify(zflag: bool, forest_flag: bool, maximum: float, medium_threshold: float = 4) -> Severity:
    if zflag and forest_flag:
        return Severity.CRITICAL
    if forest_flag:
        return Severity.HIGH
    if zflag:
        return Severity.MEDIUM if maximum > medium_threshold else Severity.LOW
    return Severity.NORMAL


class DetectionEngine:
    """Evaluate against history, then call observe ONLY after successful persistence."""
    def __init__(self, config: Config):
        self.config = config
        self.baseline = RollingBaseline(config, ())
        self.zscore = ZScoreDetector(config.zscore_threshold)
        self.forest = ForestDetector(config)
        self.candidate: tuple[str, ...] | None = None
        self.candidate_count = 0
        self.since_fit = 0
        self.training_suspended = False
        self.clean_streak = 0

    def _schema(self, sample: Sample, incident_active: bool = False):
        available = tuple(k for k in METRICS if sample.values[k] is not None)
        if not self.baseline.features and available:
            self.baseline = RollingBaseline(self.config, available)
        if available != self.baseline.features:
            self.candidate_count = self.candidate_count + 1 if available == self.candidate else 1
            self.candidate = available
            if self.candidate_count >= self.config.feature_change_samples and not incident_active:
                self.baseline = RollingBaseline(self.config, available)
                self.forest = ForestDetector(self.config)
                self.since_fit = 0
                self.candidate_count = 0
        else:
            self.candidate, self.candidate_count = None, 0

    def evaluate(self, raw: Sample, incident_active: bool = False) -> Decision:
        started = time.perf_counter()
        sample = validate_sample(raw)
        self._schema(sample, incident_active)
        baseline = self.baseline.statistics()
        eligible = self.baseline.ready and all(sample.values[k] is not None for k in self.baseline.features)
        zresult, fresult = ZResult(), ForestResult(features=self.baseline.features, trained_at=self.forest.trained_at,
                                                 training_samples=self.forest.training_samples)
        severity = Severity.NORMAL
        if eligible:
            if self.forest.model is None or (self.since_fit >= self.config.retraining_interval_samples and not self.training_suspended and not incident_active):
                self.forest.fit(self.baseline, sample.timestamp.isoformat())
                self.since_fit = 0
            zresult = self.zscore.detect(sample, baseline)
            fresult = self.forest.detect(sample)
            severity = classify(zresult.anomaly, fresult.anomaly, zresult.maximum, self.config.zscore_medium_threshold)
        if not eligible:
            explanation = "Detection paused: collecting a complete historical window or waiting for valid supported inputs."
        else:
            details = [f"{LABELS[k]} is {'above' if zresult.scores[k] > 0 else 'below'} baseline (Z={zresult.scores[k]:+.2f})." for k in zresult.flagged]
            explanation = " ".join(details + [f"Z-Score {'flagged' if zresult.anomaly else 'did not flag'}; Isolation Forest {'flagged an unusual resource combination' if fresult.anomaly else 'did not flag'}. Investigation priority: {severity.value.lower()}."])
        return Decision(sample, baseline, zresult, fresult, severity, explanation, eligible, len(self.baseline.rows), self.baseline.features,
                        {"detection_ms": (time.perf_counter() - started) * 1000})

    def observe(self, decision: Decision):
        if decision.ready:
            self.since_fit += 1
            if decision.severity != Severity.NORMAL:
                self.training_suspended, self.clean_streak = True, 0
            else:
                self.clean_streak += 1
                if self.clean_streak >= self.config.recovery_samples_before_retraining:
                    self.training_suspended = False
        else:
            self.clean_streak = 0
        self.baseline.add(decision.sample)

    def step(self, sample: Sample, incident_active: bool = False) -> Decision:
        result = self.evaluate(sample, incident_active)
        self.observe(result)
        return result
