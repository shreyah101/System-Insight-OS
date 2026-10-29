"""Finite genuine telemetry recording; labels are created only by explicit demo actions."""
import argparse
import math
from pathlib import Path

from src.config import load_config
from src.runtime import MonitorService, install_signals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--config")
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    if not math.isfinite(args.minutes) or args.minutes <= 0:
        parser.error("minutes must be finite and positive")
    service = MonitorService(load_config(args.config))
    install_signals(service)
    session_id = service.run(duration=args.minutes * 60)
    print(f"Recorded session {session_id}")
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(service.repository.export_metrics(session_id), encoding="utf-8")


if __name__ == "__main__":
    main()
