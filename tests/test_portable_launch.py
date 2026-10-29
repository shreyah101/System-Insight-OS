import socket
import subprocess
import sys

import pytest

from scripts.launch import choose_port
from src.config import ROOT


def test_explicit_port_conflict_is_clear():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        with pytest.raises(ValueError, match="unavailable"):
            choose_port(occupied.getsockname()[1])


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_port(port):
    with pytest.raises(ValueError, match="between"):
        choose_port(port)


def test_default_port_is_available():
    port = choose_port()
    assert 8501 <= port <= 8511
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_bootstrap_help_works_outside_repo(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "run.py"), "--help"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0
    assert "--setup-only" in result.stdout
    assert not (tmp_path / ".venv").exists()
