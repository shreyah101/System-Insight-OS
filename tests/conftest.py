from datetime import datetime, timedelta, timezone

import pytest

from src.config import Config
from src.models import METRICS, Sample


@pytest.fixture
def config(tmp_path):
    return Config(database_path=str(tmp_path / "test.sqlite3"), rolling_window_size=6,
                  isolation_forest_estimators=20, retraining_interval_samples=3,
                  recovery_samples_before_retraining=6, incident_recovery_samples=3)


@pytest.fixture
def sample_factory():
    def factory(i=0, **values):
        data = dict(zip(METRICS, (25., 45., 20000., 15000., 140., 2.)))
        data.update(values)
        return Sample(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=2 * i), data)
    return factory
