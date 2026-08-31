"""Tests for cancellable Real-ESRGAN orchestration and bounded retries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, PipelineStage, ProgressEvent, Rational, ToolInfo, Toolchain
from advanced_ai_video_tools.services.frame_extraction import FrameExtractionResult
from advanced_ai_video_tools.services.upscaling import LIVE_PREVIEW_FRAME_INTERVAL, UpscalingCancelled, UpscalingExecutor, UpscalingFailed
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessExecutionError, ProcessResult, SubprocessRunner
from advanced_ai_video_tools.upscaling.realesrgan import MEMORY_RETRY_TILE_SIZES, REAL_IMAGE_MODEL
from advanced_ai_video_tools.video.frames import FRAME_FILENAME_TEMPLATE


def _png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 2))


def _fixture(tmp_path: Path, *, scale: int | None = 2, output_height: int = 72) -> tuple[WorkspaceManager, OwnedWorkspace, FrameExtractionResult, JobPlan, Toolchain]:
    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()
    frames = workspace.path / "frames"
    frames.mkdir()
    for number in range(1, 4):
        (frames / f"frame-{number:09d}.png").write_bytes(_png_header(64, 36))
    audio = workspace.path / "merged.mkv"
    audio.write_bytes(b"media")
    extraction_process = ProcessResult(("ffmpeg",), 0, "", "")
    extracted = FrameExtractionResult(frames, frames / FRAME_FILENAME_TEMPLATE, 3, 3, 64, 36, audio, extraction_process, workspace.identifier)
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "output.mp4", True, (), Rational(10, 1), 128, output_height, scale, ConcatStrategy.NORMALIZE, "mono", (), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"))
    models = tmp_path / "models"
    models.mkdir()
    (models / f"{REAL_IMAGE_MODEL}.param").touch()
    (models / f"{REAL_IMAGE_MODEL}.bin").touch()
    generic = ToolInfo(tmp_path / "tool", "version")
    tools = Toolchain(generic, generic, ToolInfo(tmp_path / "realesrgan-ncnn-vulkan", "usage"), models)
    return manager, workspace, extracted, job, tools


class RecordingUpscaleRunner:
    """Simulate directory inference, allocation errors, and cancellation."""

    def __init__(self, actions: Sequence[str] = ("success",)) -> None:
        self.actions = list(actions)
        self.commands: list[tuple[str, ...]] = []

    @staticmethod
    def _write_outputs(arguments: tuple[str, ...], *, short: bool = False) -> None:
        input_directory = Path(arguments[arguments.index("-i") + 1])
        output_directory = Path(arguments[arguments.index("-o") + 1])
        scale = int(arguments[arguments.index("-s") + 1])
        inputs = sorted(input_directory.glob("*.png"))
        if short:
            inputs = inputs[:-1]
        for source in inputs:
            (output_directory / source.name).write_bytes(_png_header(64 * scale, 36 * scale))

    def run(self, command: Sequence[str], cancellation: CancellationToken, _timeout_seconds: float) -> ProcessResult:
        """Apply the next scripted backend outcome."""

        arguments = tuple(command)
        self.commands.append(arguments)
        action = self.actions.pop(0)
        output_directory = Path(arguments[arguments.index("-o") + 1])
        if action == "memory":
            (output_directory / "partial.png").write_bytes(b"partial")
            raise ProcessExecutionError(arguments, 1, "", "vkAllocateMemory failed -2")
        if action == "failure":
            raise ProcessExecutionError(arguments, 1, "", "failed to load model")
        if action == "cancel":
            cancellation.cancel()
            raise ProcessCancelled("cancelled", arguments)
        self._write_outputs(arguments, short=action == "short")
        return ProcessResult(arguments, 0, "", "")


def test_upscale_success_uses_one_directory_invocation_and_retains_audio(tmp_path: Path) -> None:
    """One successful AI pass returns verified scaled frames for encoding."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner()
    events: list[ProgressEvent] = []

    result = UpscalingExecutor(manager, runner, command_timeout_seconds=5).execute(extracted, job, tools, workspace=workspace, progress=events.append)

    assert not result.skipped
    assert result.scale == 2
    assert result.frame_count == 3
    assert (result.frame_width, result.frame_height) == (128, 72)
    assert result.audio_source_path == extracted.audio_source_path
    assert len(runner.commands) == 1
    assert result.attempts[0].tile_size == 0 and result.attempts[0].succeeded
    assert [(event.stage, event.completed, event.total) for event in events] == [(PipelineStage.UPSCALE, 0, 3), (PipelineStage.UPSCALE, 3, 3)]


def test_upscale_live_preview_uses_the_latest_sixteen_frame_sample(tmp_path: Path) -> None:
    """The queue can receive only completed image samples at fixed intervals."""

    directory = tmp_path / "upscaled"
    directory.mkdir()
    initial_sample = directory / "frame-000000001.png"
    first_sample = directory / "frame-000000016.png"
    latest_sample = directory / "frame-000000032.png"
    initial_sample.write_bytes(_png_header(128, 72))
    first_sample.write_bytes(_png_header(128, 72))
    latest_sample.write_bytes(_png_header(128, 72))

    assert LIVE_PREVIEW_FRAME_INTERVAL == 16
    assert UpscalingExecutor._sampled_preview_frame(directory, 0) is None  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 1) == initial_sample  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 15) == initial_sample  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 16) == first_sample  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 31) == first_sample  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 32) == latest_sample  # pylint: disable=protected-access


def test_upscale_skip_reuses_verified_extracted_frames_without_process(tmp_path: Path) -> None:
    """Inputs already at target height bypass AI without copying frames."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path, scale=None, output_height=36)
    runner = RecordingUpscaleRunner()

    result = UpscalingExecutor(manager, runner).execute(extracted, job, tools, workspace=workspace)

    assert result.skipped
    assert result.scale is None
    assert result.frames_directory == extracted.frames_directory
    assert not result.attempts
    assert not runner.commands
    assert not (workspace.path / "upscaled").exists()


def test_pre_cancelled_skip_is_still_a_cancelled_stage(tmp_path: Path) -> None:
    """A pending cancellation wins even when no external AI process is needed."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path, scale=None, output_height=36)
    token = CancellationToken()
    token.cancel()

    with pytest.raises(UpscalingCancelled, match="before launch"):
        UpscalingExecutor(manager, RecordingUpscaleRunner()).execute(extracted, job, tools, workspace=workspace, cancellation=token)


def test_vulkan_memory_failure_retries_after_resetting_only_output(tmp_path: Path) -> None:
    """An allocation error moves from auto to 512 tiles without stale files."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("memory", "success"))

    result = UpscalingExecutor(manager, runner).execute(extracted, job, tools, workspace=workspace)

    assert [attempt.tile_size for attempt in result.attempts] == [0, 512]
    assert [command[command.index("-t") + 1] for command in runner.commands] == ["0", "512"]
    assert not (result.frames_directory / "partial.png").exists()
    assert extracted.frames_directory.is_dir()


def test_non_memory_failure_does_not_retry_and_preserves_diagnostics(tmp_path: Path) -> None:
    """Configuration and model failures are terminal on their first attempt."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("failure",))

    with pytest.raises(UpscalingFailed) as captured:
        UpscalingExecutor(manager, runner).execute(extracted, job, tools, workspace=workspace)

    assert len(runner.commands) == 1
    assert captured.value.diagnostic_tail == "failed to load model"
    assert len(captured.value.attempts) == 1
    assert workspace.path.is_dir()


def test_memory_retries_are_bounded_and_record_every_attempt(tmp_path: Path) -> None:
    """Persistent allocation failure exhausts the documented finite sequence."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("memory",) * 6)

    with pytest.raises(UpscalingFailed) as captured:
        UpscalingExecutor(manager, runner).execute(extracted, job, tools, workspace=workspace)

    assert [attempt.tile_size for attempt in captured.value.attempts] == [0, *MEMORY_RETRY_TILE_SIZES]
    assert len(runner.commands) == 6


def test_upscale_output_must_match_the_input_frame_set_exactly(tmp_path: Path) -> None:
    """A missing output frame fails without retrying an unrelated error."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("short",))

    with pytest.raises(UpscalingFailed, match="frame count differs"):
        UpscalingExecutor(manager, runner).execute(extracted, job, tools, workspace=workspace)

    assert len(runner.commands) == 1


def test_upscale_cancellation_preserves_caller_owned_workspace(tmp_path: Path) -> None:
    """Cancellation is typed and leaves final cleanup to the job owner."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("cancel",))

    with pytest.raises(UpscalingCancelled) as captured:
        UpscalingExecutor(manager, runner).execute(extracted, job, tools, workspace=workspace)

    assert captured.value.workspace_path == workspace.path
    assert workspace.path.is_dir()
    assert len(captured.value.attempts) == 1


def test_fake_executable_contract_runs_through_cancellable_process_boundary(tmp_path: Path) -> None:
    """The real process adapter can drive a lightweight directory-mode backend."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    executable = tmp_path / "fake-realesrgan"
    executable.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys
arguments = sys.argv[1:]
if any(flag in arguments for flag in ('-g', '-j', '-x')):
    raise SystemExit(9)
required = ('-i', '-o', '-m', '-n', '-s', '-t', '-f')
if any(flag not in arguments for flag in required) or arguments[arguments.index('-n') + 1] != 'realesrgan-x4plus' or arguments[arguments.index('-f') + 1] != 'png':
    raise SystemExit(8)
source_directory = pathlib.Path(arguments[arguments.index('-i') + 1])
output_directory = pathlib.Path(arguments[arguments.index('-o') + 1])
scale = int(arguments[arguments.index('-s') + 1])
for source in source_directory.glob('frame-*.png'):
    data = bytearray(source.read_bytes())
    width = int.from_bytes(data[16:20], 'big') * scale
    height = int.from_bytes(data[20:24], 'big') * scale
    data[16:20] = width.to_bytes(4, 'big')
    data[20:24] = height.to_bytes(4, 'big')
    (output_directory / source.name).write_bytes(data)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    tools = Toolchain(tools.ffmpeg, tools.ffprobe, ToolInfo(executable, "fake"), tools.model_directory)

    result = UpscalingExecutor(manager, SubprocessRunner(), command_timeout_seconds=5).execute(extracted, job, tools, workspace=workspace)

    assert result.frame_count == 3
    assert (result.frame_width, result.frame_height) == (128, 72)
