"""Unit tests for opt-in native hardware acceptance gating."""

from __future__ import annotations

import subprocess

import pytest

from advanced_ai_video_tools.system.hardware import _default_runner, apple_silicon_metal_error
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


@pytest.mark.parametrize("failure", [OSError("missing profiler"), subprocess.TimeoutExpired("system_profiler", 15.0)])
def test_metal_gate_reports_runner_exception(failure: Exception) -> None:
    """Profiler launch failures become actionable native-test skip reasons."""

    def runner(_arguments: object, _timeout: float) -> subprocess.CompletedProcess[str]:
        raise failure

    error = apple_silicon_metal_error(info=PlatformInfo("Darwin", "arm64", "26.5.2"), runner=runner)

    assert error is not None
    assert "could not inspect Metal support" in error


@pytest.mark.parametrize("stdout", ["", "not json"])
def test_metal_gate_reports_malformed_profiler_json(stdout: str) -> None:
    """Malformed profiler output never enables native acceptance."""

    result = _result(stdout=stdout)

    error = apple_silicon_metal_error(info=PlatformInfo("Darwin", "arm64", "26.5.2"), runner=lambda _arguments, _timeout: result)

    assert error is not None
    assert "invalid Metal data" in error


def test_metal_gate_uses_expected_profiler_command_contract() -> None:
    """The native capability query keeps its exact shell-free contract."""

    calls: list[tuple[object, float]] = []

    def runner(arguments: object, timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append((arguments, timeout))
        return _result(stdout='{"SPDisplaysDataType": [{"spdisplays_metal": "Metal 4"}]}')

    assert apple_silicon_metal_error(info=PlatformInfo("Darwin", "arm64", "26.5.2"), runner=runner) is None
    assert calls == [(("/usr/sbin/system_profiler", "SPDisplaysDataType", "-json"), 15.0)]


def test_default_runner_uses_shell_free_subprocess_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production runner passes the native query without a shell."""

    calls: list[tuple[object, dict[str, object]]] = []

    def run(arguments: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((arguments, kwargs))
        return _result(stdout="{}")

    monkeypatch.setattr(subprocess, "run", run)

    _default_runner(("/usr/sbin/system_profiler", "SPDisplaysDataType", "-json"), 15.0)

    assert calls == [
        (
            ["/usr/sbin/system_profiler", "SPDisplaysDataType", "-json"],
            {"check": False, "capture_output": True, "text": True, "timeout": 15.0, "shell": False},
        )
    ]


@pytest.mark.parametrize("info", [PlatformInfo("Darwin", "x86_64", "26.5.2"), PlatformInfo("Linux", "arm64", "26.5.2")])
def test_metal_gate_does_not_run_profiler_on_unsupported_platform(info: PlatformInfo) -> None:
    """Platform rejection happens before any native command is launched."""

    called = False

    def runner(_arguments: object, _timeout: float) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return _result(stdout="{}")

    assert apple_silicon_metal_error(info=info, runner=runner) is not None
    assert not called
