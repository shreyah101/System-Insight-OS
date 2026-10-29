from types import SimpleNamespace as NS
from datetime import datetime

import pytest
import psutil

from src.models import METRICS, Sample
from src.telemetry import Collector, validate_sample, top_processes


class FakeAPI:
    def __init__(self):
        self.read, self.write, self.swap_total = 1000, 2000, 100
    def cpu_percent(self, interval=None):
        return 25.
    def virtual_memory(self):
        return NS(percent=45)
    def swap_memory(self):
        return NS(total=self.swap_total, percent=2)
    def pids(self):
        return [1, 2, 3]
    def disk_io_counters(self, **kwargs):
        return NS(read_bytes=self.read, write_bytes=self.write)


def test_first_cpu_and_disk_discarded():
    sample = Collector(api=FakeAPI()).collect()
    assert sample.values["cpu_percent"] is None
    assert sample.values["disk_read_bps"] is None
    assert sample.timestamp.utcoffset().total_seconds() == 0


def test_rates_use_actual_elapsed():
    api = FakeAPI()
    clock = iter([10., 14.])
    collector = Collector(api=api, clock=lambda: next(clock))
    collector.collect()
    api.read, api.write = 1800, 3200
    sample = collector.collect()
    assert sample.values["disk_read_bps"] == 200
    assert sample.values["disk_write_bps"] == 300
    assert sample.values["cpu_percent"] == 25
    assert sample.values["process_count"] == 3
    assert sample.elapsed_seconds == 4


def test_counter_reset_and_missing_swap():
    api = FakeAPI()
    clock = iter([0., 2., 4.])
    collector = Collector(api=api, clock=lambda: next(clock))
    collector.collect()
    api.read, api.write, api.swap_total = 10, 20, 0
    sample = collector.collect()
    assert sample.values["disk_read_bps"] is None
    assert sample.quality["disk_read_bps"] == "disk counter reset"
    assert sample.values["swap_percent"] is None
    api.read, api.write = 30, 60
    assert collector.collect().values["disk_write_bps"] == 20


def test_unavailable_disk_and_access_errors():
    api = FakeAPI()
    api.disk_io_counters = lambda **kwargs: None
    def denied():
        raise psutil.AccessDenied()
    api.virtual_memory = denied
    sample = Collector(api=api).collect()
    assert sample.values["ram_percent"] is None
    assert sample.values["disk_read_bps"] is None
    assert sample.values["process_count"] == 3


@pytest.mark.parametrize("metric,value", [("cpu_percent", 101), ("ram_percent", -1), ("swap_percent", float("nan")), ("disk_read_bps", float("inf")), ("process_count", 2.2), ("cpu_percent", True)])
def test_invalid_values_individually_rejected(sample_factory, metric, value):
    result = validate_sample(sample_factory(**{metric: value}))
    assert result.values[metric] is None
    assert result.quality[metric] == "invalid reading"


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone"):
        validate_sample(Sample(datetime(2026, 1, 1), dict.fromkeys(METRICS, 0)))


def test_zero_elapsed_disk_interval():
    clock = iter([2., 2.])
    collector = Collector(api=FakeAPI(), clock=lambda: next(clock))
    collector.collect()
    assert collector.collect().values["disk_read_bps"] is None


def test_disappearing_process(monkeypatch):
    class Vanished:
        @property
        def info(self):
            raise psutil.NoSuchProcess(42)
    monkeypatch.setattr(psutil, "process_iter", lambda *a, **k: [Vanished(), NS(info={"pid": 1, "name": "good", "memory_info": NS(rss=2**20), "status": "sleeping"})])
    assert top_processes() == [{"PID": 1, "Name": "good", "RAM MiB": 1., "Status": "sleeping"}]
