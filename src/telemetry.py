"""Read-only host telemetry. No process is modified by this module."""
from __future__ import annotations

import math
import platform
import socket
import time
from datetime import datetime, timezone

import psutil

from src.models import METRICS, Sample, utc_now


def validate_sample(sample: Sample) -> Sample:
    if sample.timestamp.tzinfo is None or sample.timestamp.utcoffset() is None:
        raise ValueError("Sample timestamps must be timezone-aware")
    values, quality = {}, dict(sample.quality)
    for key in METRICS:
        value = sample.values.get(key)
        if value is None:
            values[key] = None
            quality.setdefault(key, "unavailable")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (key.endswith("percent") and value > 100) or (key == "process_count" and value != int(value)):
            values[key], quality[key] = None, "invalid reading"
        else:
            values[key], quality[key] = float(value), "valid"
    return Sample(sample.timestamp.astimezone(timezone.utc), values, quality, sample.elapsed_seconds)


class Collector:
    def __init__(self, api=psutil, clock=time.monotonic, now=utc_now):
        self.api, self.clock, self.now = api, clock, now
        self.previous_disk = None
        self.previous_time = None
        self.cpu_primed = False

    def collect(self) -> Sample:
        current = self.clock()
        elapsed = None if self.previous_time is None else current - self.previous_time
        values = {key: None for key in METRICS}
        quality = {}

        def read(key, fn):
            try:
                values[key] = fn()
            except (psutil.Error, OSError, RuntimeError, NotImplementedError) as exc:
                quality[key] = f"unavailable: {type(exc).__name__}"

        def cpu():
            value = self.api.cpu_percent(interval=None)
            if not self.cpu_primed:
                self.cpu_primed = True
                quality["cpu_percent"] = "initial CPU interval discarded"
                return None
            return value

        read("cpu_percent", cpu)
        read("ram_percent", lambda: self.api.virtual_memory().percent)
        read("process_count", lambda: len(self.api.pids()))

        def swap():
            result = self.api.swap_memory()
            if result.total <= 0:
                quality["swap_percent"] = "not applicable: no configured swap"
                return None
            return result.percent

        read("swap_percent", swap)
        try:
            disk = self.api.disk_io_counters(nowrap=False)
            for key, attr in (("disk_read_bps", "read_bytes"), ("disk_write_bps", "write_bytes")):
                if disk is None or self.previous_disk is None or elapsed is None or elapsed <= 0:
                    quality[key] = "unavailable disk interval"
                else:
                    delta = getattr(disk, attr) - getattr(self.previous_disk, attr)
                    if delta < 0:
                        quality[key] = "disk counter reset"
                    else:
                        values[key] = delta / elapsed
            self.previous_disk = disk
        except (psutil.Error, OSError, RuntimeError, NotImplementedError) as exc:
            self.previous_disk = None
            for key in ("disk_read_bps", "disk_write_bps"):
                quality[key] = f"unavailable: {type(exc).__name__}"
        self.previous_time = current
        return validate_sample(Sample(self.now(), values, quality, elapsed))


def system_metadata() -> dict:
    def safe(fn):
        try:
            return fn()
        except (psutil.Error, OSError, RuntimeError, NotImplementedError):
            return None
    return {"hostname": socket.gethostname(), "os": platform.platform(), "python": platform.python_version(),
            "logical_cores": safe(lambda: psutil.cpu_count()), "physical_cores": safe(lambda: psutil.cpu_count(logical=False)),
            "total_ram_bytes": safe(lambda: psutil.virtual_memory().total),
            "boot_time": safe(lambda: datetime.fromtimestamp(psutil.boot_time(), timezone.utc).isoformat())}


def top_processes(limit: int = 10) -> list[dict]:
    rows = []
    for process in psutil.process_iter(["pid", "name", "memory_info", "status"], ad_value=None):
        try:
            info = process.info
            mem = info.get("memory_info")
            rows.append({"PID": info["pid"], "Name": info["name"], "RAM MiB": mem.rss / 2**20 if mem else None, "Status": info.get("status")})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(rows, key=lambda r: r["RAM MiB"] or 0, reverse=True)[:limit]
