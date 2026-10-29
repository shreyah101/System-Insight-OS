"""Launch this laptop's collector and dashboard; Ctrl+C stops owned children."""
import argparse
import importlib.util
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def choose_port(requested: int | None = None) -> int:
    for port in [requested] if requested is not None else range(8501, 8512):
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise ValueError(f"Port {requested} is unavailable" if requested is not None else "No free port from 8501 to 8511; choose another using --port")


def stop_children(children):
    for child in children:
        if child.poll() is None:
            try:
                child.send_signal(signal.CTRL_BREAK_EVENT) if os.name == "nt" else child.terminate()
                child.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired):
                child.kill()
                child.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start this laptop's collector and local dashboard")
    parser.add_argument("--port", type=int, help="Dashboard port (default: first free port from 8501 to 8511)")
    parser.add_argument("--config", type=Path, help="Shared configuration for both processes")
    args = parser.parse_args(argv)
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, interrupted)
    missing = [module for module in ("psutil", "numpy", "pandas", "sklearn", "streamlit", "plotly", "yaml") if importlib.util.find_spec(module) is None]
    if missing:
        parser.exit(2, "Missing dependencies: " + ", ".join(missing) + ". Run python run.py to set up this clone.\n")
    from src.config import load_config
    from src.runtime import FileLock, WorkerAlreadyRunning
    config_path = (args.config or Path(os.environ.get("SYSTEM_INSIGHT_CONFIG", ROOT / "config.yaml"))).resolve()
    try:
        config = load_config(config_path)
        port = choose_port(args.port)
        with FileLock(config.db_path.with_suffix(".monitor.lock")):
            pass
    except (ValueError, OSError, WorkerAlreadyRunning) as exc:
        parser.exit(2, f"Cannot launch: {exc}\n")
    env = os.environ.copy()
    env["SYSTEM_INSIGHT_CONFIG"] = str(config_path)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    children, exit_code = [], 0
    print(f"System Insight OS: http://127.0.0.1:{port}\nMonitoring this laptop. Press Ctrl+C to stop both components.", flush=True)
    commands = (["-m", "scripts.run_monitor", "--config", str(config_path)],
                ["-m", "streamlit", "run", str(ROOT / "app.py"), "--server.address", "127.0.0.1", "--server.port", str(port)])
    try:
        for command in commands:
            children.append(subprocess.Popen([sys.executable, *command], cwd=ROOT, env=env, creationflags=flags))
        while True:
            stopped = next((child for child in children if child.poll() is not None), None)
            if stopped is not None:
                exit_code = stopped.returncode
                if exit_code:
                    print(f"A component exited with code {exit_code}; stopping the other component.", file=sys.stderr)
                break
            try:
                children[0].wait(timeout=.5)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"Cannot start application: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        stop_children(children)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
