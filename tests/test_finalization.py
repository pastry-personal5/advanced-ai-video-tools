"""Tests for terminal encoding, verification, publication, and cleanup."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, MediaProbe, OverwriteMode, PipelineStage, ProgressEvent, Rational, ToolInfo, Toolchain, VideoStream
from ai_video_tools.services.finalization import FinalOutputVerifier, FinalizationCancelled, FinalizationExecutor, FinalizationFailed
from ai_video_tools.services.media_preparation import PreparationResult
from ai_video_tools.services.upscaling import UpscalingResult
from ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceManager
from ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessExecutionError, ProcessResult


def _png_header(width: int = 64, height: int = 36) -> bytes:
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 2))


def _video(*, width: int = 64, rate: Rational = Rational(10, 1), time_base: Rational = Rational(1, 10240)) -> VideoStream:
    return VideoStream(0, "h264", width, 36, "yuv420p", Rational(1, 1), rate, rate, time_base, Decimal("1"), "bt709", "bt709", "bt709", "tv", 0, False)


class FinalProbe:
    """Return deterministic final facts at the requested partial path."""

    def __init__(self, *, width: int = 64, rate: Rational = Rational(10, 1), time_base: Rational = Rational(1, 10240), race_destination: Path | None = None) -> None:
        self.width = width
        self.rate = rate
        self.time_base = time_base
        self.race_destination = race_destination

    def probe(self, path: Path) -> MediaProbe:
        """Optionally simulate another publisher winning after encoding."""

        if self.race_destination is not None:
            self.race_destination.write_bytes(b"racing winner")
        return MediaProbe(path, Decimal("1"), (_video(width=self.width, rate=self.rate, time_base=self.time_base),), (), ())


class FinalRunner:
    """Materialize a fake encoded partial or a typed process outcome."""

    def __init__(self, *, fail: bool = False, cancel: bool = False) -> None:
        self.fail = fail
        self.cancel = cancel
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str], cancellation: CancellationToken, _timeout_seconds: float) -> ProcessResult:
        """Record one shell-free command and write its final argument."""

        arguments = tuple(command)
        self.commands.append(arguments)
        if self.cancel:
            cancellation.cancel()
            raise ProcessCancelled("cancelled", arguments)
        if self.fail:
            raise ProcessExecutionError(arguments, 1, "", "synthetic final encode failure")
        Path(arguments[-1]).write_bytes(b"encoded partial")
        return ProcessResult(arguments, 0, "", "")


def _inputs(tmp_path: Path, *, generated: bool = False, overwrite: OverwriteMode = OverwriteMode.REPLACE) -> tuple[WorkspaceManager, OwnedWorkspace, PreparationResult, UpscalingResult, JobPlan, Toolchain]:
    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()
    frames = workspace.path / "frames"
    frames.mkdir()
    for number in range(1, 11):
        (frames / f"frame-{number:09d}.png").write_bytes(_png_header())
    merged_path = workspace.path / "merged.mkv"
    merged_path.write_bytes(b"merged")
    merged_video = VideoStream(0, "ffv1", 64, 36, "yuv444p10le", Rational(1, 1), Rational(10, 1), Rational(10, 1), Rational(1, 1000), Decimal("1"), "bt709", "bt709", "bt709", "tv", 0, False)
    merged = MediaProbe(merged_path, Decimal("1"), (merged_video,), (), ())
    prepared = PreparationResult(merged, 1, (), workspace.identifier)
    upscaled = UpscalingResult(frames, frames / "frame-%09d.png", 10, 64, 36, None, True, None, (), workspace.identifier)
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "final.mp4", generated, (), Rational(10, 1), 64, 36, None, ConcatStrategy.NORMALIZE, None, (), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"), overwrite_mode=overwrite)
    toolchain = Toolchain(ToolInfo(Path("ffmpeg"), "ffmpeg fake"), ToolInfo(Path("ffprobe"), "ffprobe fake"), ToolInfo(Path("realesrgan"), "realesrgan fake"), tmp_path / "models")
    return manager, workspace, prepared, upscaled, job, toolchain


def test_success_verifies_publishes_replaces_and_cleans_workspace(tmp_path: Path) -> None:
    """Only a verified partial can replace an explicit destination."""

    manager, workspace, prepared, upscaled, job, toolchain = _inputs(tmp_path)
    job.output_path.write_bytes(b"old output")
    runner = FinalRunner()
    events: list[ProgressEvent] = []
    executor = FinalizationExecutor(manager, runner, FinalOutputVerifier(FinalProbe()), command_timeout_seconds=5)

    result = executor.execute(prepared, upscaled, job, toolchain, workspace=workspace, progress=events.append)

    assert result.output_path == job.output_path
    assert result.output_probe.path == job.output_path
    assert job.output_path.read_bytes() == b"encoded partial"
    assert not workspace.path.exists()
    assert len(runner.commands) == 1
    assert [event.stage for event in events if event.completed == event.total] == [PipelineStage.ENCODE, PipelineStage.VERIFY, PipelineStage.PUBLISH, PipelineStage.CLEANUP]


def test_final_verifier_accepts_rate_rounding_below_one_timestamp_tick(tmp_path: Path) -> None:
    """A representational rate fraction does not block safe publication."""

    manager, workspace, prepared, upscaled, job, toolchain = _inputs(tmp_path)
    executor = FinalizationExecutor(manager, FinalRunner(), FinalOutputVerifier(FinalProbe(rate=Rational(10001, 1000), time_base=Rational(1, 1000))), command_timeout_seconds=5)

    result = executor.execute(prepared, upscaled, job, toolchain, workspace=workspace)

    assert result.output_path == job.output_path
    assert not workspace.path.exists()


def test_encode_failure_preserves_old_output_and_workspace_but_discards_partial(tmp_path: Path) -> None:
    """A failed child process cannot damage the last complete destination."""

    manager, workspace, prepared, upscaled, job, toolchain = _inputs(tmp_path)
    job.output_path.write_bytes(b"old output")
    executor = FinalizationExecutor(manager, FinalRunner(fail=True), FinalOutputVerifier(FinalProbe()), command_timeout_seconds=5)

    with pytest.raises(FinalizationFailed) as captured:
        executor.execute(prepared, upscaled, job, toolchain, workspace=workspace)

    assert captured.value.stage is PipelineStage.ENCODE
    assert captured.value.diagnostic_tail == "synthetic final encode failure"
    assert job.output_path.read_bytes() == b"old output"
    assert workspace.path.is_dir()
    assert not tuple(tmp_path.glob(".*.partial.mp4"))


def test_verification_failure_preserves_destination_and_diagnostic_workspace(tmp_path: Path) -> None:
    """Structurally invalid output is removed before it can be published."""

    manager, workspace, prepared, upscaled, job, toolchain = _inputs(tmp_path)
    job.output_path.write_bytes(b"old output")
    executor = FinalizationExecutor(manager, FinalRunner(), FinalOutputVerifier(FinalProbe(width=32)), command_timeout_seconds=5)

    with pytest.raises(FinalizationFailed, match="dimensions differ") as captured:
        executor.execute(prepared, upscaled, job, toolchain, workspace=workspace)

    assert captured.value.stage is PipelineStage.VERIFY
    assert job.output_path.read_bytes() == b"old output"
    assert workspace.path.is_dir()
    assert not tuple(tmp_path.glob(".*.partial.mp4"))


def test_cancellation_discards_partial_and_cleans_owned_workspace(tmp_path: Path) -> None:
    """Cancellation is terminal cleanup, not a retained processing failure."""

    manager, workspace, prepared, upscaled, job, toolchain = _inputs(tmp_path)
    job.output_path.write_bytes(b"old output")
    executor = FinalizationExecutor(manager, FinalRunner(cancel=True), FinalOutputVerifier(FinalProbe()), command_timeout_seconds=5)

    with pytest.raises(FinalizationCancelled, match="workspace cleaned") as captured:
        executor.execute(prepared, upscaled, job, toolchain, workspace=workspace)

    assert captured.value.stage is PipelineStage.ENCODE
    assert captured.value.workspace_path == workspace.path
    assert job.output_path.read_bytes() == b"old output"
    assert not workspace.path.exists()
    assert not tuple(tmp_path.glob(".*.partial.mp4"))


@pytest.mark.parametrize(("generated", "overwrite"), [(True, OverwriteMode.REPLACE), (False, OverwriteMode.NO_OVERWRITE)])
def test_no_clobber_modes_reject_a_publication_race(tmp_path: Path, generated: bool, overwrite: OverwriteMode) -> None:
    """Generated names and explicit no-overwrite both enforce atomic no-clobber."""

    manager, workspace, prepared, upscaled, job, toolchain = _inputs(tmp_path, generated=generated, overwrite=overwrite)
    executor = FinalizationExecutor(manager, FinalRunner(), FinalOutputVerifier(FinalProbe(race_destination=job.output_path)), command_timeout_seconds=5)

    with pytest.raises(FinalizationFailed, match="appeared") as captured:
        executor.execute(prepared, upscaled, job, toolchain, workspace=workspace)

    assert captured.value.stage is PipelineStage.PUBLISH
    assert job.output_path.read_bytes() == b"racing winner"
    assert workspace.path.is_dir()
    assert not tuple(tmp_path.glob(".*.partial.mp4"))
