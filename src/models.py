from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

METRICS = ("cpu_percent", "ram_percent", "disk_read_bps", "disk_write_bps", "process_count", "swap_percent")
LABELS = dict(zip(METRICS, ("CPU usage", "RAM usage", "Disk read", "Disk write", "Processes", "Swap usage")))
UNITS = dict(zip(METRICS, ("%", "%", "B/s", "B/s", "processes", "%")))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Severity(str, Enum):
    NORMAL = "NORMAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_ORDER = list(Severity)


@dataclass
class Sample:
    timestamp: datetime
    values: dict[str, float | None]
    quality: dict[str, str] = field(default_factory=dict)
    elapsed_seconds: float | None = None


@dataclass
class BaselineStat:
    mean: float
    std: float
    effective_std: float
    count: int


@dataclass
class ZResult:
    scores: dict[str, float] = field(default_factory=dict)
    flagged: list[str] = field(default_factory=list)
    observed: dict[str, float] = field(default_factory=dict)
    baseline: dict[str, BaselineStat] = field(default_factory=dict)

    @property
    def maximum(self) -> float:
        return max((abs(z) for z in self.scores.values()), default=0.0)

    @property
    def anomaly(self) -> bool:
        return bool(self.flagged)


@dataclass
class ForestResult:
    ready: bool = False
    anomaly: bool = False
    score: float | None = None
    features: tuple[str, ...] = ()
    trained_at: str | None = None
    training_samples: int = 0


@dataclass
class Decision:
    sample: Sample
    baseline: dict[str, BaselineStat]
    zscore: ZResult
    forest: ForestResult
    severity: Severity
    explanation: str
    ready: bool
    warmup_count: int
    features: tuple[str, ...]
    timing: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["sample"]["timestamp"] = self.sample.timestamp.isoformat()
        result["severity"] = self.severity.value
        return result
