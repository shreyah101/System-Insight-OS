"""Portable, standard-library-only bootstrap: python run.py."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv
import signal

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set up and run System Insight OS on this laptop")
    parser.add_argument("--setup-only", action="store_true", help="Install dependencies without starting monitoring")
    parser.add_argument("--install", action="store_true", help="Install/update requirements in the local virtual environment")
    parser.add_argument("--port", type=int, help="Use a specific local dashboard port")
    parser.add_argument("--config", type=Path, help="Use an alternate configuration file")
    args = parser.parse_args(argv)
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, interrupted)
    if sys.version_info < (3, 11):
        parser.exit(2, "Python 3.11 or newer is required. Install Python, then rerun this command.\n")
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    created = not python.exists()
    try:
        if created:
            print("Creating this clone's isolated .venv...", flush=True)
            venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
        pip_check = subprocess.run([str(python), "-c", "import pip"], cwd=ROOT,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if pip_check.returncode:
            subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], cwd=ROOT, check=True)
        check = subprocess.run([str(python), "-c", "import psutil,numpy,pandas,sklearn,streamlit,plotly,yaml"],
                               cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if created or check.returncode or args.install or args.setup_only:
            print("Installing requirements into .venv (internet is needed on first setup)...", flush=True)
            subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], cwd=ROOT, check=True)
        if args.setup_only:
            print("Setup complete. Run python run.py to start monitoring this laptop.", flush=True)
            return 0
        command = [str(python), "-m", "scripts.launch"]
        if args.port is not None:
            command.extend(["--port", str(args.port)])
        if args.config:
            command.extend(["--config", str(args.config.resolve())])
        child = subprocess.Popen(command, cwd=ROOT,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                                 start_new_session=os.name != "nt")
        try:
            # A finite wait lets Windows dispatch SIGBREAK while the launcher
            # is running. An indefinite wait can delay the handler forever.
            while True:
                try:
                    return child.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    pass
        except KeyboardInterrupt:
            if child.poll() is None:
                child.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                return 1
            return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}\nCheck internet access and that this folder is writable.\n"
              "On Linux, install your distribution's python3-venv package if venv/ensurepip is missing.\n"
              "Retry with: python run.py --install", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
