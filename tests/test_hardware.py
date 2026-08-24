"""Unit tests for opt-in native hardware acceptance gating."""

from __future__ import annotations

import subprocess

from advanced_ai_video_tools.system.hardware import apple_silicon_metal_error
from advanced_ai_video_tools.system.platform import PlatformInfo


def _result(*, stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(("system_profiler",), returncode, stdout, stderr)


def test_metal_gate_accepts_apple_reported_metal_support() -> None:
    """A supported Apple Silicon report enables native acceptance checks."""

    result = _result(stdout='{"SPDisplaysDataType": [{"spdisplays_metal": "Metal 4"}]}')
    current_result = _result(stdout='{"SPDisplaysDataType": [{"spdisplays_mtlgpufamilysupport": "spdisplays_metal4"}]}')

    assert apple_silicon_metal_error(info=PlatformInfo("Darwin", "arm64", "26.5.2"), runner=lambda _arguments, _timeout: result) is None
    assert apple_silicon_metal_error(info=PlatformInfo("Darwin", "arm64", "26.5.2"), runner=lambda _arguments, _timeout: current_result) is None


def test_metal_gate_rejects_missing_or_unsupported_capability() -> None:
    """A profile without usable Metal cannot accidentally enable the benchmark."""

    unsupported = _result(stdout='{"SPDisplaysDataType": [{"spdisplays_metal": "Not Supported"}]}')

    assert "Metal support" in (apple_silicon_metal_error(info=PlatformInfo("Darwin", "arm64", "26.5.2"), runner=lambda _arguments, _timeout: unsupported) or "")
    assert "Apple Silicon" in (apple_silicon_metal_error(info=PlatformInfo("Darwin", "x86_64", "26.5.2"), runner=lambda _arguments, _timeout: unsupported) or "")


def test_metal_gate_reports_profiler_failure() -> None:
    """Profiler errors remain actionable instead of being treated as a pass."""

    failed = _result(stdout="", stderr="permission denied", returncode=1)

    assert "permission denied" in (apple_silicon_metal_error(info=PlatformInfo("Darwin", "arm64", "26.5.2"), runner=lambda _arguments, _timeout: failed) or "")
