"""Discovery and bounded launch validation for user-installed media tools."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from ai_video_tools.core.models import ToolInfo, Toolchain, ToolOverrides

CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]

_SMOKE_TEST_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAACXBIWXMAAAABAAAAAQBPJcTWAAAAGUlEQVR4nGNsaGhgIAWwkKR6VMOohiGlAQD3PAG+dQ2rPwAAAABJRU5ErkJggg==")


class ToolDiscoveryError(RuntimeError):
    """A required executable or model asset could not be validated."""


def _default_runner(arguments: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


class ToolDiscovery:
    """Resolve explicit locations before PATH and validate required assets."""

    def __init__(self, runner: CommandRunner = _default_runner) -> None:
        self._runner = runner
        self._validated_backends: set[tuple[Path, Path]] = set()

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

    def _inspect(self, name: str, path: Path, argument: str) -> ToolInfo:
        try:
            result = self._runner((str(path), argument), 10.0)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ToolDiscoveryError(f"could not launch {name}: {error}") from error
        combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if result.returncode != 0:
            detail = combined.strip().splitlines()
            suffix = f": {detail[0]}" if detail else ""
            raise ToolDiscoveryError(f"{name} validation failed{suffix}")
        first_line = next((line.strip() for line in combined.splitlines() if line), "")
        return ToolInfo(path=path, version=first_line or "version unavailable")

    def discover(self, overrides: ToolOverrides) -> Toolchain:
        """Resolve executables, prove they launch, and check x4plus model files."""

        ffmpeg_path = self._resolve("ffmpeg", overrides.ffmpeg)
        ffprobe_path = self._resolve("ffprobe", overrides.ffprobe)
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
        return Toolchain(
            ffmpeg=self._inspect("ffmpeg", ffmpeg_path, "-version"),
            ffprobe=self._inspect("ffprobe", ffprobe_path, "-version"),
            realesrgan=self._inspect("realesrgan-ncnn-vulkan", realesrgan_path, "-h"),
            model_directory=resolved_model_directory,
        )

    def _validate_realesrgan_backend(self, executable: Path, model_directory: Path) -> None:
        cache_key = (executable, model_directory)
        if cache_key in self._validated_backends:
            return
        with tempfile.TemporaryDirectory(prefix="ai-video-tools-preflight-") as raw:
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
                result = self._runner(arguments, 60.0)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ToolDiscoveryError(f"Real-ESRGAN Vulkan smoke test could not run: {error}") from error
            if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
                combined = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
                detail = combined.splitlines()[0] if combined else "no output image"
                raise ToolDiscoveryError("Real-ESRGAN Vulkan smoke test failed: " + detail)
        self._validated_backends.add(cache_key)
