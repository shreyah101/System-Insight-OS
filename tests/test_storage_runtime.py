import csv
import io
import json
import sqlite3
from datetime import timedelta
from dataclasses import replace
from threading import Thread

import pytest

from src.config import Config, load_config
from src.detection import DetectionEngine
from src.models import Severity
from src.models import utc_now
from src.runtime import FileLock, MonitorService, WorkerAlreadyRunning, monitor_status
from src.storage import Repository


def setup_repo(config):
    repo = Repository(config.db_path)
    repo.initialize()
    session = repo.start_session({}, {})
    return repo, session


def ready_decision(config, sample_factory, severity="NORMAL"):
    result = DetectionEngine(config).step(sample_factory())
    result.ready = True
    result.severity = Severity(severity)
    result.zscore.flagged = ["cpu_percent"] if severity in ("LOW", "MEDIUM", "CRITICAL") else []
    result.forest.anomaly = severity in ("HIGH", "CRITICAL")
    result.forest.score = -.1 if result.forest.anomaly else .1
    return result


def test_storage_restart_queries_and_csv(config, sample_factory):
    repo, session = setup_repo(config)
    result = ready_decision(config, sample_factory, "CRITICAL")
    repo.save(session, result, 3)
    restarted = Repository(config.db_path)
    rows = restarted.metrics(session)
    assert len(rows) == 1
    assert rows[0]["forest_score"] == -.1
    assert json.loads(rows[0]["decision_json"])["sample"]["values"]["cpu_percent"] == 25
    assert len(list(csv.DictReader(io.StringIO(restarted.export_metrics(session))))) == 1
    assert restarted.summary(session)["samples"] == 1
    assert restarted.alerts(session, detector="forest", severity="CRITICAL")
    assert restarted.metrics(session, start="2099-01-01T00:00:00+00:00") == []
    assert restarted.session(session)["source"] == "live"


def test_foreign_keys_and_rollback(config, sample_factory):
    repo, session = setup_repo(config)
    with pytest.raises(sqlite3.IntegrityError):
        repo.save("missing", ready_decision(config, sample_factory), 3)
    assert repo.summary(session)["samples"] == 0


def test_episodes_deduplicate_escalate_recover(config, sample_factory):
    repo, session = setup_repo(config)
    for severity in ("LOW", "LOW", "CRITICAL", "HIGH"):
        repo.save(session, ready_decision(config, sample_factory, severity), 3)
    alerts = repo.alerts(session)
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "CRITICAL"
    assert alerts[0]["occurrence_count"] == 4
    assert alerts[0]["z_flag"] and alerts[0]["forest_flag"]
    for _ in range(2):
        repo.save(session, ready_decision(config, sample_factory), 3)
    assert repo.active(session)
    repo.save(session, ready_decision(config, sample_factory), 3)
    assert not repo.active(session)
    assert repo.alerts(session)[0]["status"] == "Resolved"
    repo.save(session, ready_decision(config, sample_factory, "HIGH"), 3)
    assert len(repo.alerts(session)) == 2
    assert len(repo.metrics(session)) == 8


def test_missing_data_cannot_resolve_episode(config, sample_factory):
    repo, session = setup_repo(config)
    repo.save(session, ready_decision(config, sample_factory, "LOW"), 3)
    for _ in range(10):
        repo.save(session, DetectionEngine(config).step(sample_factory()), 3)
    assert repo.active(session)
    assert repo.alerts(session)[0]["recovery_count"] == 0


def test_lock_rejects_duplicate_and_releases(config):
    path = config.db_path.with_suffix(".lock")
    with FileLock(path):
        with pytest.raises(WorkerAlreadyRunning):
            with FileLock(path):
                pass
    with FileLock(path):
        pass


def test_monitor_fault_recovery_and_restart(config, sample_factory):
    class FakeCollector:
        n = 0
        def collect(self):
            self.n += 1
            if self.n == 1:
                raise OSError("transient")
            return sample_factory(self.n)
    cfg = replace(config, sampling_interval_seconds=.01)
    service = MonitorService(cfg, FakeCollector())
    session = service.run(max_samples=8, duration=5)
    assert len(service.repository.metrics(session)) == 8
    assert service.repository.session(session)["status"] == "stopped"
    newer = MonitorService(cfg, FakeCollector()).run(max_samples=2, duration=5)
    assert newer != session
    assert len(service.repository.metrics(session)) == 8
    assert service.repository.metrics(session)[-1]["ready"]
    assert monitor_status(service.repository.session(session), service.repository.metrics(session)[-1], cfg) == "Offline"


def test_safe_shutdown(config, sample_factory):
    class FakeCollector:
        def collect(self):
            return sample_factory()
    service = MonitorService(config, FakeCollector())
    thread = Thread(target=service.run)
    thread.start()
    service.stop()
    thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize("changes", [{"rolling_window_size": 0}, {"sampling_interval_seconds": -1}, {"isolation_forest_contamination": .8}, {"zscore_medium_threshold": 2}, {"minimum_std": {}}, {"demo_memory_mb": 1000}, {"retention": "delete"}, {"rolling_window_size": 4.5}, {"sampling_interval_seconds": float("nan")}, {"random_seed": -1}])
def test_invalid_configuration(changes):
    with pytest.raises(ValueError):
        Config(**changes)


def test_central_config_loads_and_unknown_fails(tmp_path):
    assert load_config().rolling_window_size == 60
    path = tmp_path / "bad.yaml"
    path.write_text("typo: true", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown"):
        load_config(path)


def test_status_states(config, sample_factory):
    assert monitor_status(None, None, config) == "Offline"
    session = {"status": "running", "heartbeat": utc_now().isoformat()}
    assert monitor_status(session, None, config) == "Initializing"
    row = {"ready": 0, "severity": "NORMAL", "decision_json": json.dumps(DetectionEngine(config).step(sample_factory()).to_dict())}
    assert monitor_status(session, row, config) == "Warming up"
    row["ready"] = 1
    assert monitor_status(session, row, config) == "Healthy"
    row["severity"] = "CRITICAL"
    assert monitor_status(session, row, config) == "Anomaly detected"
    session["status"] = "error"
    assert monitor_status(session, row, config) == "Collector error"
    session["heartbeat"] = (utc_now() - timedelta(seconds=100)).isoformat()
    assert monitor_status(session, row, config) == "Stale data"


@pytest.mark.parametrize("options", [{"duration": float("nan")}, {"duration": float("inf")}, {"duration": -1}, {"max_samples": 0}, {"max_samples": 2.5}])
def test_invalid_run_limits_rejected(config, options):
    with pytest.raises(ValueError):
        MonitorService(config).run(**options)
    assert not config.db_path.exists()
