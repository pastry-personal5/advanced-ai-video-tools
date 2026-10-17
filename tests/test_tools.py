"""Tests for external prerequisite discovery."""

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import ToolOverrides
from advanced_ai_video_tools.system import spandrel
from advanced_ai_video_tools.system.processes import ProcessOutputLimitError
from advanced_ai_video_tools.system.tools import ModelCompatibilityError, ToolDiscovery, ToolDiscoveryError


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

    def denied_runner(arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        if "-i" in arguments:
            raise PermissionError("operation not permitted")
        return subprocess.CompletedProcess(arguments, 0, "tool version 1", "")

    with pytest.raises(ToolDiscoveryError, match="Real-ESRGAN Vulkan smoke test could not run: operation not permitted"):
        ToolDiscovery(denied_runner).discover(ToolOverrides(executable, executable, executable, models))


def test_tool_validation_rejects_oversized_output(tmp_path: Path) -> None:
    """A configured tool cannot exhaust memory by writing unbounded output."""

    executable = _executable(tmp_path / "tool")
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()

    def oversized(_arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        raise ProcessOutputLimitError(1024)

    with pytest.raises(ToolDiscoveryError, match="1,024-byte"):
        ToolDiscovery(oversized).discover(ToolOverrides(executable, executable, executable, models))


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
    assert sum(1 for command in logged if "-i" in command and "-o" in command) == 1
    assert logged.count((str(executable.resolve()), "-version")) == 2
    assert logged.count((str(executable.resolve()), "-h")) == 1


def test_selective_discovery_inspects_only_required_spandrel_model(tmp_path: Path) -> None:
    """Pipeline-aware discovery does not inspect an unused model slot."""

    ffmpeg = _executable(tmp_path / "ffmpeg")
    ffprobe = _executable(tmp_path / "ffprobe")
    runner = _executable(tmp_path / "spandrel-runner")
    model = tmp_path / "DAT_x2.safetensors"
    model.write_bytes(b"model")
    calls: list[tuple[str, ...]] = []

    def command_runner(arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        args = tuple(arguments)
        calls.append(args)
        if "inspect" in args:
            stat = model.stat()
            payload = {
                "protocol_version": 1,
                "runner_version": "0.4.0",
                "model_identity": {"path": str(model.resolve()), "device": stat.st_dev, "inode": stat.st_ino, "size_bytes": stat.st_size, "modified_ns": stat.st_mtime_ns, "sha256": hashlib.sha256(model.read_bytes()).hexdigest()},
                "architecture": "DAT",
                "purpose": "SR",
                "input_channels": 3,
                "output_channels": 3,
                "scale": 2,
                "size_requirements": {"minimum": 1, "multiple_of": 1, "square": False},
                "maximum_input_pixels": 1000,
                "device": "mps",
                "precision": "float32",
            }
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(args, 0, "version", "")

    discovery = ToolDiscovery(command_runner)
    overrides = ToolOverrides(ffmpeg=ffmpeg, ffprobe=ffprobe, spandrel_runner=runner, model_2x=model)
    media = discovery.discover_media(overrides)
    tools = discovery.complete_for_passes(overrides, media, require_realesrgan=False, spandrel_scales=(2,))

    assert tools.realesrgan is None and tools.model_directory is None
    assert tools.spandrel_runner is not None and tools.spandrel_runner.path == runner.resolve()
    assert [item.scale for item in tools.spandrel_inspections] == [2]
    assert not any("realesrgan" in argument for call in calls for argument in call)


def _spandrel_tools(tmp_path: Path) -> tuple[ToolOverrides, Path]:
    model = tmp_path / "DAT_x2.safetensors"
    model.write_bytes(b"model")
    overrides = ToolOverrides(ffmpeg=_executable(tmp_path / "ffmpeg"), ffprobe=_executable(tmp_path / "ffprobe"), spandrel_runner=_executable(tmp_path / "spandrel-runner"), model_2x=model)
    return overrides, model


def test_failed_model_inspection_reports_the_runner_error_code(tmp_path: Path) -> None:
    """The runner's stable error record becomes the actionable compatibility message."""

    overrides, _model = _spandrel_tools(tmp_path)
    stderr = '{"code": "incompatible_model", "event": "error", "message": "model must be an RGB 2x or 3x super-resolution descriptor"}\n'

    def runner(arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        if "inspect" in arguments:
            return subprocess.CompletedProcess(arguments, 3, "", stderr)
        return subprocess.CompletedProcess(arguments, 0, "version", "")

    discovery = ToolDiscovery(runner)
    media = discovery.discover_media(overrides)
    with pytest.raises(ModelCompatibilityError, match="incompatible_model: model must be an RGB"):
        discovery.complete_for_passes(overrides, media, require_realesrgan=False, spandrel_scales=(2,))


def test_inspection_for_the_wrong_scale_is_a_model_compatibility_error(tmp_path: Path) -> None:
    """A 3x descriptor in the 2x slot is rejected without falling back to another model."""

    overrides, model = _spandrel_tools(tmp_path)
    stat = model.stat()
    payload = {
        "protocol_version": 1,
        "runner_version": "0.4.0",
        "model_identity": {"path": str(model.resolve()), "device": stat.st_dev, "inode": stat.st_ino, "size_bytes": stat.st_size, "modified_ns": stat.st_mtime_ns, "sha256": "a" * 64},
        "architecture": "DAT",
        "purpose": "SR",
        "input_channels": 3,
        "output_channels": 3,
        "scale": 3,
        "size_requirements": {"minimum": 1, "multiple_of": 1, "square": False},
        "maximum_input_pixels": 1000,
        "device": "mps",
        "precision": "float32",
    }

    def runner(arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, json.dumps(payload) if "inspect" in arguments else "version", "")

    discovery = ToolDiscovery(runner)
    with pytest.raises(ModelCompatibilityError, match="RGB 2x"):
        discovery.complete_for_passes(overrides, discovery.discover_media(overrides), require_realesrgan=False, spandrel_scales=(2,))


class _InspectingRunner:
    """Answer `--help` and `inspect` for models whose scale is known by file name."""

    def __init__(self, scales: dict[str, int]) -> None:
        self.scales = scales
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, arguments: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        args = tuple(arguments)
        self.calls.append(args)
        if "inspect" not in args:
            return subprocess.CompletedProcess(args, 0, "version", "")
        model = Path(args[args.index("--model") + 1])
        stat = model.stat()
        payload = {
            "protocol_version": 1,
            "runner_version": "0.5.0",
            "model_identity": {"path": str(model.resolve()), "device": stat.st_dev, "inode": stat.st_ino, "size_bytes": stat.st_size, "modified_ns": stat.st_mtime_ns, "sha256": hashlib.sha256(model.read_bytes()).hexdigest()},
            "architecture": "DAT",
            "purpose": "SR",
            "input_channels": 3,
            "output_channels": 3,
            "scale": self.scales[model.name],
            "size_requirements": {"minimum": 1, "multiple_of": 1, "square": False},
            "maximum_input_pixels": 1000,
            "device": "mps",
            "precision": "float32",
        }
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    def launched(self) -> set[str]:
        """Return every executable the discovery layer started."""

        return {call[0] for call in self.calls}


def _default_layout(tmp_path: Path, *, models: bool = True) -> tuple[Path, Path]:
    """Build a throwaway checkout layout and return its runner and models directory."""

    runner_directory = tmp_path / "checkout" / "tools" / "spandrel-runner"
    models_directory = runner_directory / "models"
    models_directory.mkdir(parents=True)
    runner = _executable(runner_directory / "spandrel-runner")
    if models:
        for name in spandrel.DEFAULT_SPANDREL_MODELS.values():
            (models_directory / name).write_bytes(f"weights of {name}".encode())
    return runner, models_directory


def _media_overrides(tmp_path: Path, **changes: Path) -> ToolOverrides:
    return ToolOverrides(ffmpeg=_executable(tmp_path / "ffmpeg"), ffprobe=_executable(tmp_path / "ffprobe"), **changes)


def _path_decoy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a different `spandrel-runner` on PATH, which a default must never pick up."""

    directory = tmp_path / "on-path"
    directory.mkdir()
    decoy = _executable(directory / "spandrel-runner")
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ.get('PATH', '')}")
    return decoy


_SCALES_BY_DEFAULT_NAME = {name: scale for scale, name in spandrel.DEFAULT_SPANDREL_MODELS.items()}


def test_the_factory_default_pair_matches_the_documented_selection() -> None:
    """Changing a default file is a documented decision, so the exact names are pinned."""

    assert spandrel.DEFAULT_SPANDREL_MODELS == {2: "2xPublic_realplksr_dysample_layernorm_real_nn.pth", 3: "DAT_x3_bf16.safetensors"}


def test_the_default_runner_is_the_checkout_launcher_whatever_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The default is anchored to the installed source tree, never to the current directory."""

    monkeypatch.chdir(tmp_path)
    expected = Path(__file__).resolve().parents[1] / "tools" / "spandrel-runner" / "spandrel-runner"

    assert spandrel.DEFAULT_SPANDREL_RUNNER == expected
    assert spandrel.DEFAULT_SPANDREL_RUNNER.is_absolute()
    assert spandrel.DEFAULT_SPANDREL_RUNNER.is_file() and os.access(spandrel.DEFAULT_SPANDREL_RUNNER, os.X_OK)


def test_unset_runner_and_models_use_the_factory_defaults_and_never_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing configured, the default launcher and its default models serve both slots."""

    runner, models = _default_layout(tmp_path)
    decoy = _path_decoy(tmp_path, monkeypatch)
    fake = _InspectingRunner(_SCALES_BY_DEFAULT_NAME)
    overrides = _media_overrides(tmp_path)
    discovery = ToolDiscovery(fake, default_spandrel_runner=runner)

    tools = discovery.complete_for_passes(overrides, discovery.discover_media(overrides), require_realesrgan=False, spandrel_scales=(2, 3))

    assert tools.spandrel_runner is not None and tools.spandrel_runner.path == runner.resolve()
    assert [(item.scale, item.model_identity.path) for item in tools.spandrel_inspections] == [(scale, (models / name).resolve()) for scale, name in spandrel.DEFAULT_SPANDREL_MODELS.items()]
    assert str(decoy.resolve()) not in fake.launched()


def test_an_explicit_runner_moves_the_default_models_beside_it(tmp_path: Path) -> None:
    """Unset models follow the runner that will load them, as Real-ESRGAN's models directory does."""

    default_runner, _default_models = _default_layout(tmp_path)
    custom_directory = tmp_path / "custom"
    (custom_directory / "models").mkdir(parents=True)
    custom_runner = _executable(custom_directory / "spandrel-runner")
    custom_model = custom_directory / "models" / spandrel.DEFAULT_SPANDREL_MODELS[2]
    custom_model.write_bytes(b"custom weights")
    fake = _InspectingRunner(_SCALES_BY_DEFAULT_NAME)
    overrides = _media_overrides(tmp_path, spandrel_runner=custom_runner)
    discovery = ToolDiscovery(fake, default_spandrel_runner=default_runner)

    tools = discovery.complete_for_passes(overrides, discovery.discover_media(overrides), require_realesrgan=False, spandrel_scales=(2,))

    assert tools.spandrel_runner is not None and tools.spandrel_runner.path == custom_runner.resolve()
    assert [item.model_identity.path for item in tools.spandrel_inspections] == [custom_model.resolve()]
    assert default_runner.resolve() not in {Path(command) for command in fake.launched()}


def test_an_explicit_model_wins_over_the_factory_default(tmp_path: Path) -> None:
    """A configured file is used even when the default file exists, and the other slot still defaults."""

    runner, models = _default_layout(tmp_path)
    explicit = tmp_path / "my-2x.safetensors"
    explicit.write_bytes(b"my weights")
    fake = _InspectingRunner({**_SCALES_BY_DEFAULT_NAME, explicit.name: 2})
    overrides = _media_overrides(tmp_path, model_2x=explicit)
    discovery = ToolDiscovery(fake, default_spandrel_runner=runner)

    tools = discovery.complete_for_passes(overrides, discovery.discover_media(overrides), require_realesrgan=False, spandrel_scales=(2, 3))

    assert [item.model_identity.path for item in tools.spandrel_inspections] == [explicit.resolve(), (models / spandrel.DEFAULT_SPANDREL_MODELS[3]).resolve()]


def test_a_missing_default_model_names_the_expected_path_and_the_override(tmp_path: Path) -> None:
    """The failure says exactly where the default file belongs and how to choose another."""

    runner, models = _default_layout(tmp_path, models=False)
    overrides = _media_overrides(tmp_path)
    discovery = ToolDiscovery(_InspectingRunner(_SCALES_BY_DEFAULT_NAME), default_spandrel_runner=runner)
    expected = models / spandrel.DEFAULT_SPANDREL_MODELS[3]

    with pytest.raises(ToolDiscoveryError, match=re.escape(str(expected))) as caught:
        discovery.complete_for_passes(overrides, discovery.discover_media(overrides), require_realesrgan=False, spandrel_scales=(3,))

    assert "--model-3x" in str(caught.value) and "Settings" in str(caught.value)


def test_a_missing_default_runner_is_actionable_and_ignores_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A source tree without the launcher fails with its path instead of using PATH."""

    absent = tmp_path / "no-checkout" / "tools" / "spandrel-runner" / "spandrel-runner"
    decoy = _path_decoy(tmp_path, monkeypatch)
    fake = _InspectingRunner({})
    overrides = _media_overrides(tmp_path)
    discovery = ToolDiscovery(fake, default_spandrel_runner=absent)

    with pytest.raises(ToolDiscoveryError, match=re.escape(str(absent))) as caught:
        discovery.complete_for_passes(overrides, discovery.discover_media(overrides), require_realesrgan=False, spandrel_scales=(2,))

    assert "--spandrel-runner" in str(caught.value)
    assert str(decoy.resolve()) not in fake.launched()


def test_unused_factory_defaults_never_block_other_pipelines(tmp_path: Path) -> None:
    """Absent default files matter only to a pass that needs them."""

    absent = tmp_path / "no-checkout" / "tools" / "spandrel-runner" / "spandrel-runner"
    overrides = _media_overrides(tmp_path)
    discovery = ToolDiscovery(_InspectingRunner({}), default_spandrel_runner=absent)

    tools = discovery.complete_for_passes(overrides, discovery.discover_media(overrides), require_realesrgan=False, validate_configured_runner=True)

    assert tools.spandrel_runner is None and not tools.spandrel_inspections
