"""Explicitly started, conservative demonstrations in an isolated subprocess."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from src.config import Config, ROOT
from src.models import utc_now
from src.runtime import FileLock
from src.storage import Repository

KINDS = ("CPU activity", "Memory growth", "Disk I/O activity", "Process activity")


def limits(config: Config) -> dict:
    return {"seconds": config.demo_max_seconds, "memory_mb": config.demo_memory_mb,
            "disk_file_mb": config.demo_disk_mb, "disk_total_write_mb": 64,
            "children": config.demo_process_count, "cpu_duty": config.demo_cpu_duty}


def launch(repository: Repository, config: Config, scenario: str, session_id: str | None) -> str:
    if scenario not in KINDS:
        raise ValueError("Unsupported demonstration")
    event_id = repository.create_workload(scenario, limits(config), session_id)
    try:
        subprocess.Popen([sys.executable, "-m", "src.workloads", "--database", str(repository.path), "--event", event_id],
                         cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except Exception as exc:
        repository.update_workload(event_id, status="failed", ended_at=utc_now().isoformat(), error=str(exc))
        raise
    return event_id


def execute(repository: Repository, event_id: str):
    children, memory = [], []
    status, error = "completed", None
    try:
        with FileLock(repository.path.with_suffix(".workload.lock")):
            event = repository.workload(event_id)
            plan = json.loads(event["limits_json"])
            # Revalidate stored limits, even if invoked directly at the command line.
            if event["scenario"] not in KINDS or not (0 < plan["seconds"] <= 60 and 0 < plan["memory_mb"] <= 128 and 0 < plan["disk_file_mb"] <= 16 and 0 < plan["children"] <= 4 and 0 < plan["cpu_duty"] <= .5 and 0 < plan["disk_total_write_mb"] <= 64):
                raise ValueError("Unsafe workload limits")
            repository.update_workload(event_id, status="running", started_at=utc_now().isoformat())
            start = time.monotonic()
            scenario = event["scenario"]
            # Sleeping children have their own hard timeout, even if this controller is killed.
            if scenario == "Process activity":
                for _ in range(plan["children"]):
                    children.append(subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({plan['seconds'] + 1})"],
                                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
            with tempfile.TemporaryDirectory(prefix="system-insight-demo-") as temp:
                disk_path = Path(temp) / "bounded-demo.bin"
                written, last_disk = 0, -1.
                while (elapsed := time.monotonic() - start) < plan["seconds"]:
                    if repository.workload(event_id)["cancel_requested"]:
                        status = "cancelled"
                        break
                    if scenario == "CPU activity":
                        # At most half of one logical core. Sleep provides a bounded duty cycle.
                        until = time.monotonic() + .1 * plan["cpu_duty"]
                        value = 1
                        while time.monotonic() < until:
                            value = (value * 1664525 + 1013904223) % 2**32
                        time.sleep(.1 * (1 - plan["cpu_duty"]))
                    elif scenario == "Memory growth":
                        target = min(plan["memory_mb"], int((elapsed / plan["seconds"]) * plan["memory_mb"]) + 1)
                        while len(memory) < target:
                            memory.append(bytearray(b"x" * 2**20))
                        time.sleep(.1)
                    elif scenario == "Disk I/O activity":
                        if elapsed - last_disk >= 1 and written < plan["disk_total_write_mb"]:
                            size = min(plan["disk_file_mb"], plan["disk_total_write_mb"] - written)
                            with disk_path.open("wb") as f:
                                f.write(b"x" * (size * 2**20))
                            with disk_path.open("rb") as f:
                                while f.read(2**20):
                                    pass
                            written, last_disk = written + size, elapsed
                        time.sleep(.1)
                    else:
                        time.sleep(.1)
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        memory.clear()
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        repository.update_workload(event_id, status=status, ended_at=utc_now().isoformat(), error=error)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--event", required=True)
    args = parser.parse_args()
    execute(Repository(args.database), args.event)
