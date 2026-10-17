"""Discovery and bounded launch validation for user-installed media tools."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from advanced_ai_video_tools.core.models import SpandrelInspection, ToolInfo, Toolchain, ToolOverrides
from advanced_ai_video_tools.system.processes import ProcessOutputLimitError, log_subprocess_launch, run_captured_subprocess
from advanced_ai_video_tools.system.spandrel import (
    DEFAULT_SPANDREL_MODELS,
    DEFAULT_SPANDREL_RUNNER,
    SpandrelProtocolError,
    create_spandrel_inspect_command,
    parse_spandrel_inspection,
    spandrel_failure_summary,
)

CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]

_SMOKE_TEST_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAACXBIWXMAAAABAAAAAQBPJcTWAAAAGUlEQVR4nGNsaGhgIAWwkKR6VMOohiGlAQD3PAG+dQ2rPwAAAABJRU5ErkJggg==")


class ToolDiscoveryError(RuntimeError):
    """A required executable or model asset could not be validated."""


class ModelCompatibilityError(ToolDiscoveryError):
    """A configured model was inspected and cannot serve its pipeline slot."""


def _default_runner(arguments: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return run_captured_subprocess(arguments, timeout)


class ToolDiscovery:
    """Resolve explicit locations before PATH and validate required assets."""

    def __init__(self, runner: CommandRunner = _default_runner, *, default_spandrel_runner: Path = DEFAULT_SPANDREL_RUNNER) -> None:
        self._runner = runner
        self._default_spandrel_runner = default_spandrel_runner
        self._validated_backends: set[tuple[Path, Path]] = set()
        self._spandrel_inspections: dict[tuple[Path, Path, int], SpandrelInspection] = {}

    @staticmethod
    def _resolve(name: str, explicit: Path | None) -> Path:
        if explicit is not None:
            candidate = explicit.expanduser()
            source = "configured path"
        else:
            found = shutil.which(name)
            if found is None:
                raise ToolDiscoveryError(f"{name} was not found. Install it or configure its " "executable path.")
            candidate = Path(found)
            source = "PATH"
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise ToolDiscoveryError(f"{name} from {source} is not an executable file: {candidate}")
        return candidate.resolve()

    def _inspect(self, name: str, path: Path, argument: str, nonzero_success_marker: str | None = None) -> ToolInfo:
        arguments = (str(path), argument)
        try:
            log_subprocess_launch(arguments)
            result = self._runner(arguments, 10.0)
        except (OSError, ProcessOutputLimitError, subprocess.TimeoutExpired) as error:
            raise ToolDiscoveryError(f"could not launch {name}: {error}") from error
        combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if result.returncode != 0 and (nonzero_success_marker is None or nonzero_success_marker not in combined):
            detail = combined.strip().splitlines()
            suffix = f": {detail[0]}" if detail else ""
            raise ToolDiscoveryError(f"{name} validation failed{suffix}")
        first_line = next((line.strip() for line in combined.splitlines() if line), "")
        return ToolInfo(path=path, version=first_line or "version unavailable")

    def discover(self, overrides: ToolOverrides) -> Toolchain:
        """Validate every configured tool, as the Settings dialog presents them."""

        media = self.discover_media(overrides)
        configured_scales = tuple(scale for scale, model in ((2, overrides.model_2x), (3, overrides.model_3x)) if model is not None)
        return self.complete_for_passes(overrides, media, require_realesrgan=True, spandrel_scales=configured_scales, validate_configured_runner=True)

    def discover_media(self, overrides: ToolOverrides) -> Toolchain:
        """Resolve only FFmpeg and FFprobe, which every job needs for probing."""

        ffmpeg_path = self._resolve("ffmpeg", overrides.ffmpeg)
        ffprobe_path = self._resolve("ffprobe", overrides.ffprobe)
        return Toolchain(
            ffmpeg=self._inspect("ffmpeg", ffmpeg_path, "-version"),
            ffprobe=self._inspect("ffprobe", ffprobe_path, "-version"),
            realesrgan=None,
            model_directory=None,
        )

    def complete_for_passes(
        self,
        overrides: ToolOverrides,
        media: Toolchain,
        *,
        require_realesrgan: bool,
        spandrel_scales: Sequence[int] = (),
        validate_configured_runner: bool = False,
    ) -> Toolchain:
        """Add exactly the AI prerequisites that a frozen pass list requires."""

        realesrgan: ToolInfo | None = None
        resolved_model_directory: Path | None = None
        if require_realesrgan:
            realesrgan, resolved_model_directory = self._discover_realesrgan(overrides)
        runner_info: ToolInfo | None = None
        inspections: list[SpandrelInspection] = []
        selected_scales = tuple(dict.fromkeys(spandrel_scales))
        if selected_scales or (validate_configured_runner and overrides.spandrel_runner is not None):
            runner_path = self._resolve_spandrel_runner(overrides)
            runner_info = self._inspect("spandrel-runner", runner_path, "--help")
            for scale in selected_scales:
                model = {2: overrides.model_2x, 3: overrides.model_3x}[scale]
                inspections.append(self._inspect_spandrel_model(runner_path, model if model is not None else self._default_spandrel_model(runner_path, scale), scale))
        return Toolchain(media.ffmpeg, media.ffprobe, realesrgan, resolved_model_directory, runner_info, tuple(inspections))

    def _resolve_spandrel_runner(self, overrides: ToolOverrides) -> Path:
        """Use the configured runner, else the factory-default launcher; never search PATH."""

        if overrides.spandrel_runner is not None:
            return self._resolve("spandrel-runner", overrides.spandrel_runner)
        default = self._default_spandrel_runner
        if not default.is_file() or not os.access(default, os.X_OK):
            raise ToolDiscoveryError(f"The factory-default Spandrel runner is not an executable file: {default}. Choose a runner in Settings or pass --spandrel-runner.")
        return default.resolve()

    @staticmethod
    def _default_spandrel_model(runner: Path, scale: int) -> Path:
        """Return the factory-default checkpoint for a scale, beside the resolved runner."""

        model = runner.parent / "models" / DEFAULT_SPANDREL_MODELS[scale]
        if not model.is_file():
            raise ToolDiscoveryError(f"The factory-default Spandrel {scale}x model is missing: {model}. Place it there, or choose a .safetensors or .pth checkpoint in Settings or pass --model-{scale}x.")
        return model

    def _discover_realesrgan(self, overrides: ToolOverrides) -> tuple[ToolInfo, Path]:
        """Resolve and prove the existing Real-ESRGAN Vulkan backend."""

        realesrgan_path = self._resolve("realesrgan-ncnn-vulkan", overrides.realesrgan)
        model_directory = overrides.model_directory.expanduser() if overrides.model_directory is not None else realesrgan_path.parent / "models"
        required = (
            model_directory / "realesrgan-x4plus.param",
            model_directory / "realesrgan-x4plus.bin",
        )
        missing = tuple(path for path in required if not path.is_file())
        if missing:
            names = ", ".join(path.name for path in missing)
            raise ToolDiscoveryError(f"Real-ESRGAN model directory {model_directory} is missing: {names}")
        resolved_model_directory = model_directory.resolve()
        self._validate_realesrgan_backend(realesrgan_path, resolved_model_directory)
        return self._inspect("realesrgan-ncnn-vulkan", realesrgan_path, "-h", "Usage: realesrgan-ncnn-vulkan"), resolved_model_directory

    def _inspect_spandrel_model(self, runner: Path, model: Path, scale: int) -> SpandrelInspection:
        """Run one exact model inspection and cache only its immutable identity."""

        model_path = model.expanduser()
        if not model_path.is_file():
            raise ToolDiscoveryError(f"Spandrel {scale}x model is not a readable file: {model_path}")
        cache_key = (runner, model_path.resolve(), scale)
        cached = self._spandrel_inspections.get(cache_key)
        if cached is not None:
            try:
                stat = model_path.stat()
            except OSError:
                cached = None
            else:
                identity = cached.model_identity
                if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != (identity.device, identity.inode, identity.size_bytes, identity.modified_ns):
                    cached = None
        if cached is not None:
            return cached
        try:
            arguments = create_spandrel_inspect_command(runner, model_path)
        except SpandrelProtocolError as error:
            raise ModelCompatibilityError(f"Spandrel {scale}x model {model_path.name} is unsupported: {error}") from error
        try:
            log_subprocess_launch(arguments)
            result = self._runner(arguments, 120.0)
        except (OSError, ProcessOutputLimitError, subprocess.TimeoutExpired) as error:
            raise ToolDiscoveryError(f"Spandrel {scale}x model inspection could not run: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            summary = spandrel_failure_summary(result.stderr) or (detail[-1] if detail else "")
            message = f"Spandrel {scale}x model inspection failed" + (f": {summary}" if summary else "")
            # An unavailable MPS device is the host's fault, not the checkpoint's.
            raise (ToolDiscoveryError if summary.startswith("mps_unavailable") else ModelCompatibilityError)(message)
        try:
            inspection = parse_spandrel_inspection(result.stdout, expected_model=model_path, expected_scale=scale)
        except SpandrelProtocolError as error:
            raise ModelCompatibilityError(str(error)) from error
        self._spandrel_inspections[cache_key] = inspection
        return inspection

    def _validate_realesrgan_backend(self, executable: Path, model_directory: Path) -> None:
        cache_key = (executable, model_directory)
        if cache_key in self._validated_backends:
            return
        with tempfile.TemporaryDirectory(prefix="advanced-ai-video-tools-preflight-") as raw:
            temporary = Path(raw)
            input_path = temporary / "input.png"
            output_path = temporary / "output.png"
            input_path.write_bytes(_SMOKE_TEST_PNG)
            arguments = (
                str(executable),
                "-i",
                str(input_path),
                "-o",
                str(output_path),
                "-m",
                str(model_directory),
                "-n",
                "realesrgan-x4plus",
                "-s",
                "4",
                "-t",
                "32",
                "-f",
                "png",
            )
            try:
                log_subprocess_launch(arguments)
                result = self._runner(arguments, 60.0)
            except (OSError, ProcessOutputLimitError, subprocess.TimeoutExpired) as error:
                raise ToolDiscoveryError(f"Real-ESRGAN Vulkan smoke test could not run: {error}") from error
            if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
                combined = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
                detail = combined.splitlines()[0] if combined else "no output image"
                raise ToolDiscoveryError("Real-ESRGAN Vulkan smoke test failed: " + detail)
        self._validated_backends.add(cache_key)
