from __future__ import annotations

import logging
import math
import os
import signal
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import psutil

from src.config import Config
from src.detection import DetectionEngine
from src.models import utc_now
from src.storage import Repository
from src.telemetry import Collector, system_metadata

log = logging.getLogger(__name__)


class WorkerAlreadyRunning(RuntimeError):
    pass


class FileLock:
    """OS advisory lock: automatically released even after a killed worker."""
    def __init__(self, path: Path):
        self.path, self.file = path, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise WorkerAlreadyRunning(f"A worker already owns {self.path}") from exc
        return self

    def __exit__(self, *_):
        if self.file:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None


class MonitorService:
    def __init__(self, config: Config, collector: Collector | None = None):
        self.config = config
        self.repository = Repository(config.db_path)
        self.collector = collector or Collector()
        self.engine = DetectionEngine(config)
        self.stop_event = threading.Event()
        self.session_id: str | None = None

    def stop(self, *_):
        self.stop_event.set()

    def run(self, max_samples: int | None = None, duration: float | None = None):
        if max_samples is not None and (type(max_samples) is not int or max_samples <= 0):
            raise ValueError("max_samples must be a positive integer")
        if duration is not None and (isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0):
            raise ValueError("duration must be a finite positive number of seconds")
        with FileLock(self.config.db_path.with_suffix(".monitor.lock")):
            self.repository.initialize()
            self.session_id = self.repository.start_session(system_metadata(), asdict(self.config), recover_abandoned=True)
            process = psutil.Process()
            process.cpu_percent(None)
            start = time.monotonic()
            due, count = start, 0
            status, error = "stopped", None
            try:
                while not self.stop_event.is_set():
                    if duration is not None and time.monotonic() - start >= duration:
                        break
                    cycle = time.monotonic()
                    try:
                        sample = self.collector.collect()
                        decision = self.engine.evaluate(sample, self.repository.active(self.session_id))
                        decision.timing.update({"sampling_lateness_ms": max(0., cycle - due) * 1000,
                                                "monitor_cpu_percent": process.cpu_percent(None),
                                                "monitor_ram_mib": process.memory_info().rss / 2**20,
                                                "monitor_uptime_seconds": cycle - start,
                                                "collection_and_detection_ms": (time.monotonic() - cycle) * 1000})
                        self.repository.save(self.session_id, decision, self.config.incident_recovery_samples)
                        self.engine.observe(decision)
                        count += 1
                        if max_samples is not None and count >= max_samples:
                            break
                    except Exception as exc:
                        log.exception("Sampling cycle failed; retrying on the next scheduled interval")
                        try:
                            self.repository.mark_error(self.session_id, f"{type(exc).__name__}: {exc}")
                        except Exception:
                            log.exception("Cannot persist collector error")
                    due += self.config.sampling_interval_seconds
                    current = time.monotonic()
                    if due < current:
                        # Skip missed deadlines without a burst of catch-up measurements.
                        due += (int((current - due) / self.config.sampling_interval_seconds) + 1) * self.config.sampling_interval_seconds
                    wait = max(0., due - current)
                    if duration is not None:
                        wait = min(wait, max(0., duration - (current - start)))
                    self.stop_event.wait(wait)
            except BaseException as exc:
                if not isinstance(exc, KeyboardInterrupt):
                    status, error = "failed", str(exc)
                    raise
            finally:
                self.repository.finish_session(self.session_id, status, error)
            return self.session_id


def install_signals(service: MonitorService):
    signal.signal(signal.SIGINT, service.stop)
    signal.signal(signal.SIGTERM, service.stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, service.stop)


def monitor_status(session: dict | None, latest: dict | None, config: Config) -> str:
    if not session or session["status"] in ("stopped", "failed", "interrupted", "completed"):
        return "Offline"
    heartbeat = datetime.fromisoformat(session["heartbeat"])
    if (utc_now() - heartbeat).total_seconds() > config.stale_after_seconds:
        return "Stale data"
    if session["status"] == "error":
        return "Collector error"
    if not latest:
        return "Initializing"
    if not latest["ready"]:
        return "Warming up" if not json_decision(latest)["forest"]["trained_at"] else "Waiting for valid data"
    return "Anomaly detected" if latest["severity"] != "NORMAL" else "Healthy"


def json_decision(row: dict) -> dict:
    import json
    return json.loads(row["decision_json"])
