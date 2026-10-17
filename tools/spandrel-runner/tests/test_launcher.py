"""The application launches the runner as an executable, not as `python main.py`."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "spandrel-runner"


def test_launcher_is_executable_and_lists_both_protocol_commands() -> None:
    assert os.access(LAUNCHER, os.X_OK)
    result = subprocess.run([str(LAUNCHER), "--help"], check=False, capture_output=True, text=True, timeout=120, shell=False)
    assert result.returncode == 0, result.stderr
    assert "inspect" in result.stdout and "run" in result.stdout


def test_launcher_preserves_the_stable_error_contract_for_a_torchscript_checkpoint(tmp_path: Path) -> None:
    model = tmp_path / "model.pt"
    model.write_bytes(b"torchscript")
    result = subprocess.run([str(LAUNCHER), "inspect", "--model", str(model), "--protocol-version", "1"], check=False, capture_output=True, text=True, timeout=120, shell=False)
    assert result.returncode == 2
    assert '"code": "invalid_request"' in result.stderr and ".safetensors or .pth" in result.stderr
