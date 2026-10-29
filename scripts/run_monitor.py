"""Run from the repository root: python -m scripts.run_monitor."""
import argparse
import logging
import math

from src.config import load_config
from src.runtime import MonitorService, WorkerAlreadyRunning, install_signals


def main():
    parser = argparse.ArgumentParser(description="Read-only local OS monitor")
    parser.add_argument("--config")
    parser.add_argument("--duration", type=float, help="Stop after this many seconds")
    parser.add_argument("--samples", type=int, help="Stop after this many persisted samples")
    args = parser.parse_args()
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0) or args.samples is not None and args.samples <= 0:
        parser.error("duration and samples must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        service = MonitorService(load_config(args.config))
        install_signals(service)
        session_id = service.run(args.samples, args.duration)
        print(f"Session saved: {session_id}", flush=True)
    except (ValueError, WorkerAlreadyRunning) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
