"""Streamlit integration checks against an isolated database, including real controls."""
import json
from dataclasses import asdict

import streamlit as st
import yaml
from streamlit.testing.v1 import AppTest

from src.config import ROOT
from src.detection import DetectionEngine
from src.models import Severity
from src.storage import Repository


def dashboard(monkeypatch, config, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(asdict(config)), encoding="utf-8")
    monkeypatch.setenv("SYSTEM_INSIGHT_CONFIG", str(path))
    st.cache_resource.clear()
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


def test_empty_dashboard(monkeypatch, config, tmp_path):
    app = dashboard(monkeypatch, config, tmp_path).run()
    assert not app.exception
    assert any("No telemetry" in item.value for item in app.info)


def test_all_dashboard_pages_and_replay(monkeypatch, config, tmp_path, sample_factory):
    repo = Repository(config.db_path)
    repo.initialize()
    session = repo.start_session({"hostname": "Test host", "os": "Test OS"}, asdict(config))
    engine = DetectionEngine(config)
    for i in range(10):
        result = engine.step(sample_factory(i, cpu_percent=90 if i == 8 else 25))
        repo.save(session, result, config.incident_recovery_samples)
    app = dashboard(monkeypatch, config, tmp_path).run()
    assert not app.exception
    for name in ["Resource explorer", "Anomaly detection", "Alert history", "Evaluation & demo lab", "System information"]:
        app.sidebar.radio[0].set_value(name).run()
        assert not app.exception, [(x.message) for x in app.exception]
        if name == "Resource explorer":
            next(box for box in app.selectbox if box.label == "Resource").set_value("disk_read_bps").run()
            assert not app.exception
        elif name == "Alert history":
            assert any("Total episodes" in metric.label for metric in app.metric)
            app.text_input[0].set_value("no such explanation").run()
            assert any("No alert episodes" in item.value for item in app.info)
        elif name == "Evaluation & demo lab":
            next(button for button in app.button if button.label == "Run replay").click().run()
            assert not app.exception
            assert app.session_state["simulation"][1]["source"] == "synthetic"
            next(button for button in app.button if button.label == "Reset simulation").click().run()
            assert "simulation" not in app.session_state
        elif name == "System information":
            assert any("Statistical anomalies" in item.value for item in app.info)
