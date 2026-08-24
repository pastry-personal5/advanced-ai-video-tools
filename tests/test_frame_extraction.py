"""Unit tests for composable frame-extraction orchestration and verification."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import AudioStream, ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, MediaProbe, PipelineStage, ProgressEvent, Rational, VideoStream
from advanced_ai_video_tools.services.frame_extraction import FrameExtractionCancelled, FrameExtractionExecutor, FrameExtractionFailed
from advanced_ai_video_tools.services.media_preparation import PreparationResult
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessExecutionError, ProcessResult


def _video() -> VideoStream:
    return VideoStream(0, "ffv1", 64, 36, "yuv444p10le", Rational(1, 1), Rational(10, 1), Rational(10, 1), Rational(1, 1000), Decimal("2"), "bt709", "bt709", "bt709", "tv", 0, False)


def _audio() -> AudioStream:
    return AudioStream(1, "pcm_s24le", 48000, 1, "mono", Decimal("2"), Rational(1, 48000))


def _prepared(workspace: OwnedWorkspace, *, has_audio: bool = True) -> tuple[PreparationResult, JobPlan]:
    merged_path = workspace.path / "merged.mkv"
    merged_path.write_bytes(b"media")
    probe = MediaProbe(merged_path, Decimal("2"), (_video(),), (_audio(),) if has_audio else (), ())
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), Path("output.mp4"), True, (probe,), Rational(10, 1), 3840, 2160, 4, ConcatStrategy.NORMALIZE, "mono" if has_audio else None, (), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"))
    return PreparationResult(probe, 0, (), workspace.identifier), job


def _png_header(width: int = 64, height: int = 36, *, color_type: int = 2) -> bytes:
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, color_type))


class RecordingExtractionRunner:
    """Create deterministic fake PNG headers or simulate process termination."""

    def __init__(self, frame_numbers: Sequence[int] = tuple(range(1, 21)), *, fail: bool = False, cancel: bool = False, color_type: int = 2) -> None:
        self.frame_numbers = tuple(frame_numbers)
        self.fail = fail
        self.cancel = cancel
        self.color_type = color_type
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str], cancellation: CancellationToken, _timeout_seconds: float) -> ProcessResult:
        """Materialize selected frame names after recording the safe command."""

        arguments = tuple(command)
        self.commands.append(arguments)
        if self.cancel:
            cancellation.cancel()
            raise ProcessCancelled("cancelled", arguments)
        if self.fail:
            raise ProcessExecutionError(arguments, 1, "", "synthetic extraction failure")
        directory = Path(arguments[-1]).parent
        for number in self.frame_numbers:
            (directory / f"frame-{number:09d}.png").write_bytes(_png_header(color_type=self.color_type))
        return ProcessResult(arguments, 0, "", "")


def _executor(tmp_path: Path, runner: RecordingExtractionRunner) -> tuple[FrameExtractionExecutor, WorkspaceManager, OwnedWorkspace]:
    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()
    return FrameExtractionExecutor(manager, runner, command_timeout_seconds=5), manager, workspace


def test_extraction_retains_frames_and_merged_audio_for_job_owner(tmp_path: Path) -> None:
    """Successful extraction reports measured inventory and performs no cleanup."""

    runner = RecordingExtractionRunner()
    executor, manager, workspace = _executor(tmp_path, runner)
    prepared, job = _prepared(workspace)
    events: list[ProgressEvent] = []

    result = executor.execute(prepared, job, Path("ffmpeg"), workspace=workspace, progress=events.append)

    assert result.frame_count == 20
    assert result.expected_frame_count == 20
    assert (result.frame_width, result.frame_height) == (64, 36)
    assert result.frame_pattern == workspace.path / "frames" / "frame-%09d.png"
    assert result.audio_source_path == workspace.path / "merged.mkv"
    assert result.audio_source_path.is_file()
    assert len(runner.commands) == 1
    assert [(event.stage, event.completed, event.total) for event in events] == [(PipelineStage.EXTRACT, 0, 20), (PipelineStage.EXTRACT, 20, 20)]
    manager.cleanup(workspace)


def test_extraction_rejects_gapped_inventory_and_retains_workspace(tmp_path: Path) -> None:
    """Noncontiguous output is a typed failure with artifacts preserved."""

    runner = RecordingExtractionRunner((1, 3))
    executor, _manager, workspace = _executor(tmp_path, runner)
    prepared, job = _prepared(workspace, has_audio=False)

    with pytest.raises(FrameExtractionFailed, match="not contiguous") as captured:
        executor.execute(prepared, job, Path("ffmpeg"), workspace=workspace)

    assert captured.value.workspace_path == workspace.path
    assert workspace.path.is_dir()
    assert (workspace.path / "frames" / "frame-000000001.png").is_file()


def test_extraction_rejects_non_rgb_png(tmp_path: Path) -> None:
    """RGBA or indexed output cannot silently enter the photographic AI stage."""

    executor, _manager, workspace = _executor(tmp_path, RecordingExtractionRunner(color_type=6))
    prepared, job = _prepared(workspace)

    with pytest.raises(FrameExtractionFailed, match="8-bit RGB"):
        executor.execute(prepared, job, Path("ffmpeg"), workspace=workspace)


def test_extraction_rejects_implausible_frame_count(tmp_path: Path) -> None:
    """A contiguous but substantially short sequence cannot enter upscaling."""

    executor, _manager, workspace = _executor(tmp_path, RecordingExtractionRunner(tuple(range(1, 18))))
    prepared, job = _prepared(workspace)

    with pytest.raises(FrameExtractionFailed, match="count differs"):
        executor.execute(prepared, job, Path("ffmpeg"), workspace=workspace)


def test_extraction_process_failure_preserves_bounded_diagnostic(tmp_path: Path) -> None:
    """Process diagnostics survive application-level error translation."""

    executor, _manager, workspace = _executor(tmp_path, RecordingExtractionRunner(fail=True))
    prepared, job = _prepared(workspace)

    with pytest.raises(FrameExtractionFailed) as captured:
        executor.execute(prepared, job, Path("ffmpeg"), workspace=workspace)

    assert captured.value.diagnostic_tail == "synthetic extraction failure"
    assert workspace.path.is_dir()


def test_extraction_cancellation_leaves_workspace_cleanup_to_job_owner(tmp_path: Path) -> None:
    """Cancellation terminates execution without deleting caller-owned state."""

    executor, manager, workspace = _executor(tmp_path, RecordingExtractionRunner(cancel=True))
    prepared, job = _prepared(workspace)

    with pytest.raises(FrameExtractionCancelled) as captured:
        executor.execute(prepared, job, Path("ffmpeg"), workspace=workspace)

    assert captured.value.workspace_path == workspace.path
    assert workspace.path.is_dir()
    manager.cleanup(workspace)
