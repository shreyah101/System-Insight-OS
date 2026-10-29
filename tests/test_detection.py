from dataclasses import replace

import numpy as np
import pytest

from src.detection import DetectionEngine, ForestDetector, RollingBaseline, ZScoreDetector, classify
from src.models import BaselineStat, METRICS, Severity


def test_baseline_math_and_bound(config, sample_factory):
    baseline = RollingBaseline(config, ("cpu_percent",))
    for i in range(8):
        baseline.add(sample_factory(i, cpu_percent=i))
    values = np.arange(2, 8)
    stat = baseline.statistics()["cpu_percent"]
    assert len(baseline.rows) == 6
    assert stat.mean == values.mean()
    assert stat.std == pytest.approx(values.std(ddof=0))
    assert baseline.ready


def test_constant_floor(config, sample_factory):
    baseline = RollingBaseline(config, ("cpu_percent",))
    for _ in range(6):
        baseline.add(sample_factory())
    stat = baseline.statistics()["cpu_percent"]
    assert stat.std == 0
    assert stat.effective_std == config.minimum_std["cpu_percent"]


@pytest.mark.parametrize("value,flag,score", [(25, False, 0), (40, False, 3), (40.1, True, 3.02), (5, True, -4), (None, False, None)])
def test_zscore_boundaries(sample_factory, value, flag, score):
    baseline = {"cpu_percent": BaselineStat(25, 5, 5, 60)}
    result = ZScoreDetector(3).detect(sample_factory(cpu_percent=value), baseline)
    assert result.anomaly == flag
    if score is None:
        assert not result.scores
    else:
        assert result.scores["cpu_percent"] == pytest.approx(score)
        assert result.maximum == pytest.approx(abs(score))


@pytest.mark.parametrize("z,f,maximum,expected", [(False, False, 0, "NORMAL"), (True, False, 3.1, "LOW"), (True, False, 4, "LOW"), (True, False, 4.001, "MEDIUM"), (False, True, 0, "HIGH"), (True, True, 9, "CRITICAL")])
def test_severity_mapping(z, f, maximum, expected):
    assert classify(z, f, maximum) == Severity(expected)


def test_previous_window_and_warmup(config, sample_factory):
    engine = DetectionEngine(config)
    for i in range(6):
        decision = engine.step(sample_factory(i))
        assert not decision.ready
        assert decision.severity == Severity.NORMAL
    result = engine.evaluate(sample_factory(6, cpu_percent=95))
    assert result.ready
    assert result.baseline["cpu_percent"].mean == 25
    assert result.zscore.scores["cpu_percent"] == 70
    assert result.forest.score is not None
    assert result.forest.training_samples == 6
    assert len(engine.baseline.rows) == 6
    assert all(r["cpu_percent"] == 25 for r in engine.baseline.rows)
    engine.observe(result)
    assert engine.baseline.statistics()["cpu_percent"].mean > 25


def test_forest_reproducibility_and_outlier(config, sample_factory):
    cfg = replace(config, rolling_window_size=60, isolation_forest_estimators=100)
    baseline = RollingBaseline(cfg, METRICS)
    rng = np.random.default_rng(7)
    for i in range(60):
        baseline.add(sample_factory(i, cpu_percent=float(rng.normal(25, 2)), ram_percent=float(rng.normal(45, .4))))
    a, b = ForestDetector(cfg), ForestDetector(cfg)
    a.fit(baseline, "fit")
    b.fit(baseline, "fit")
    result = a.detect(sample_factory(cpu_percent=99, ram_percent=99, process_count=1000))
    assert result.anomaly and result.score < 0
    assert result.score == b.detect(sample_factory(cpu_percent=99, ram_percent=99, process_count=1000)).score
    assert result.features == METRICS
    assert not a.detect(sample_factory(cpu_percent=None)).ready


def test_forest_requires_complete_window(config):
    with pytest.raises(ValueError, match="complete"):
        ForestDetector(config).fit(RollingBaseline(config, METRICS), "now")


def test_missing_features_do_not_impute(config, sample_factory):
    engine = DetectionEngine(config)
    for i in range(8):
        decision = engine.step(sample_factory(i, swap_percent=None))
    assert decision.ready
    assert "swap_percent" not in decision.features
    assert decision.sample.values["swap_percent"] is None
    previous_count = len(engine.baseline.rows)
    result = engine.step(sample_factory(9, cpu_percent=None, swap_percent=None))
    assert not result.ready
    assert len(engine.baseline.rows) == previous_count


def test_feature_schema_change_rewarms(config, sample_factory):
    engine = DetectionEngine(config)
    for i in range(8):
        engine.step(sample_factory(i))
    for i in range(config.feature_change_samples):
        decision = engine.step(sample_factory(10 + i, swap_percent=None))
    assert not decision.ready
    assert "swap_percent" not in decision.features
    assert engine.forest.model is None
    assert len(engine.baseline.rows) == 1


def test_retraining_interval_and_incident_suspension(config, sample_factory):
    engine = DetectionEngine(config)
    for i in range(6):
        engine.step(sample_factory(i))
    initial = engine.step(sample_factory(6))
    assert initial.forest.trained_at == sample_factory(6).timestamp.isoformat()
    engine.step(sample_factory(7))
    engine.step(sample_factory(8))
    retrained = engine.step(sample_factory(9))
    assert retrained.forest.trained_at == sample_factory(9).timestamp.isoformat()
    anomalous = engine.step(sample_factory(10, cpu_percent=99))
    assert anomalous.severity != Severity.NORMAL
    fit_time = anomalous.forest.trained_at
    for i in range(11, 30):
        result = engine.step(sample_factory(i, cpu_percent=99), incident_active=True)
        assert result.forest.trained_at == fit_time
    assert engine.since_fit >= config.retraining_interval_samples


def test_training_resumes_after_clean_streak(config, sample_factory):
    engine = DetectionEngine(config)
    for i in range(7):
        engine.step(sample_factory(i))
    engine.training_suspended = True
    engine.clean_streak = 0
    for i in range(config.recovery_samples_before_retraining):
        engine.step(sample_factory(8 + i))
    assert not engine.training_suspended
    old_fit = engine.forest.trained_at
    engine.step(sample_factory(30))
    assert engine.forest.trained_at != old_fit


def test_schema_refit_postponed_during_active_incident(config, sample_factory):
    engine = DetectionEngine(config)
    for i in range(7):
        engine.step(sample_factory(i))
    model = engine.forest.model
    for i in range(10):
        decision = engine.step(sample_factory(10 + i, swap_percent=None), incident_active=True)
    assert not decision.ready
    assert engine.forest.model is model
    assert "swap_percent" in engine.baseline.features
