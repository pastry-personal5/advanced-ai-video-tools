"""Tests for external prerequisite discovery."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import ToolOverrides
from advanced_ai_video_tools.system.tools import ToolDiscovery, ToolDiscoveryError


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _successful_runner(arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
    if "-o" in arguments:
        output = Path(arguments[arguments.index("-o") + 1])
        output.write_bytes(b"upscaled image")
    return subprocess.CompletedProcess(arguments, 0, "tool version 1\n", "")


def test_explicit_tools_and_x4plus_model_are_resolved(tmp_path: Path) -> None:
    """Configured locations take effect without relying on PATH."""

    ffmpeg = _executable(tmp_path / "custom-ffmpeg")
    ffprobe = _executable(tmp_path / "custom-ffprobe")
    realesrgan = _executable(tmp_path / "custom-realesrgan")
    models = tmp_path / "custom-models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()

    tools = ToolDiscovery(_successful_runner).discover(ToolOverrides(ffmpeg, ffprobe, realesrgan, models))

    assert tools.ffmpeg.path == ffmpeg.resolve()
    assert tools.realesrgan.version == "tool version 1"
    assert tools.model_directory == models.resolve()


def test_missing_model_pair_is_actionable(tmp_path: Path) -> None:
    """A partial user model installation is rejected before media work."""

    executable = _executable(tmp_path / "tool")
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()

    with pytest.raises(ToolDiscoveryError, match="realesrgan-x4plus.bin"):
        ToolDiscovery(_successful_runner).discover(ToolOverrides(executable, executable, executable, models))


def test_vulkan_smoke_test_failure_is_actionable(tmp_path: Path) -> None:
    """A launchable binary without a working backend fails discovery."""

    executable = _executable(tmp_path / "tool")
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()

    def failing_runner(arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        if "-i" in arguments:
            return subprocess.CompletedProcess(arguments, 1, "", "invalid gpu device")
        return subprocess.CompletedProcess(arguments, 0, "tool version 1", "")

    with pytest.raises(ToolDiscoveryError, match="Vulkan smoke test failed"):
        ToolDiscovery(failing_runner).discover(ToolOverrides(executable, executable, executable, models))


def test_tool_launch_permission_failure_is_actionable(tmp_path: Path) -> None:
    """A denied prerequisite launch becomes a typed discovery error."""

    executable = _executable(tmp_path / "tool")
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()

    def denied_runner(_arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        raise PermissionError("operation not permitted")

    with pytest.raises(ToolDiscoveryError, match="Real-ESRGAN Vulkan smoke test could not run: operation not permitted"):
        ToolDiscovery(denied_runner).discover(ToolOverrides(executable, executable, executable, models))


def test_realesrgan_help_usage_accepts_the_tools_nonzero_help_exit(tmp_path: Path) -> None:
    """The upstream binary's successful help text is usable despite exit 255."""

    executable = _executable(tmp_path / "tool")
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()

    def upstream_style_runner(arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        if "-o" in arguments:
            Path(arguments[arguments.index("-o") + 1]).write_bytes(b"upscaled")
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if "-h" in arguments:
            return subprocess.CompletedProcess(arguments, 255, "", "Usage: realesrgan-ncnn-vulkan -i infile -o outfile")
        return subprocess.CompletedProcess(arguments, 0, "tool version 1", "")

    tools = ToolDiscovery(upstream_style_runner).discover(ToolOverrides(executable, executable, executable, models))

    assert tools.realesrgan.version.startswith("Usage: realesrgan-ncnn-vulkan")


def test_path_fallback_discovers_standard_executable_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset overrides fall back to the user's PATH as documented."""

    ffmpeg = _executable(tmp_path / "ffmpeg")
    _executable(tmp_path / "ffprobe")
    _executable(tmp_path / "realesrgan-ncnn-vulkan")
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()
    monkeypatch.setenv("PATH", str(tmp_path))

    tools = ToolDiscovery(_successful_runner).discover(ToolOverrides())

    assert tools.ffmpeg.path == ffmpeg.resolve()
    assert tools.model_directory == models.resolve()


def test_discovery_logs_every_version_help_and_vulkan_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prerequisite checks cannot bypass exact subprocess launch logging."""

    executable = _executable(tmp_path / "custom-tool")
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()
    logged: list[tuple[str, ...]] = []
    monkeypatch.setattr("advanced_ai_video_tools.system.tools.log_subprocess_launch", lambda command: logged.append(tuple(command)))

    ToolDiscovery(_successful_runner).discover(ToolOverrides(executable, executable, executable, models))

    assert len(logged) == 4
    assert "-i" in logged[0] and "-o" in logged[0]
    assert logged[1] == (str(executable.resolve()), "-version")
    assert logged[2] == (str(executable.resolve()), "-version")
    assert logged[3] == (str(executable.resolve()), "-h")
