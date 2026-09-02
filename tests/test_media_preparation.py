"""Unit tests for preparation orchestration, progress, cleanup, and retention."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, MediaProbe, PipelineStage, ProgressEvent, Rational, VideoStream
from advanced_ai_video_tools.services.media_preparation import MediaPreparationExecutor, MergedOutputVerificationError, MergedOutputVerifier, PreparationCancelled, PreparationFailed
from advanced_ai_video_tools.storage.workspaces import WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessExecutionError, ProcessResult


def _video(*, width: int = 64, duration: Decimal = Decimal("1"), codec: str = "h264", rate: Rational = Rational(10, 1), average_rate: Rational | None = None, time_base: Rational = Rational(1, 10240)) -> VideoStream:
    return VideoStream(0, codec, width, 36, "yuv420p", Rational(1, 1), rate, average_rate or rate, time_base, duration, "bt709", "bt709", "bt709", "tv", 0, False)


def _probe(path: Path, *, width: int = 64) -> MediaProbe:
    return MediaProbe(path, Decimal("1"), (_video(width=width),), (), ())


def _job() -> JobPlan:
    probes = (_probe(Path("one.mp4")), _probe(Path("two.mp4"), width=96))
    return JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), Path("output.mp4"), True, probes, Rational(10, 1), 3840, 2160, 4, ConcatStrategy.NORMALIZE, None, ("dimensions differ",), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"))


def _merged(path: Path, *, width: int = 64) -> MediaProbe:
    return MediaProbe(path, Decimal("2"), (_video(width=width, duration=Decimal("2"), codec="ffv1"),), (), ())


class FakeProber:
    """Return one prepared merged probe."""

    def __init__(self, width: int = 64) -> None:
        self.width = width

    def probe(self, path: Path) -> MediaProbe:
        """Return deterministic merged facts."""

        return _merged(path, width=self.width)


class RecordingRunner:
    """Create expected outputs while recording command order."""

    def __init__(self, *, fail_at: int | None = None, cancel_at: int | None = None) -> None:
        self.fail_at = fail_at
        self.cancel_at = cancel_at
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...], cancellation: CancellationToken, _timeout_seconds: float) -> ProcessResult:
        """Simulate success, failure, or cancellation at a selected invocation."""

        arguments = tuple(command)
        self.commands.append(arguments)
        invocation = len(self.commands)
        if invocation == self.cancel_at:
            cancellation.cancel()
            raise ProcessCancelled("cancelled", arguments)
        if invocation == self.fail_at:
            raise ProcessExecutionError(arguments, 1, "", "synthetic failure")
        output = Path(arguments[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"media")
        return ProcessResult(arguments, 0, "", "")


def _executor(tmp_path: Path, runner: RecordingRunner, *, merged_width: int = 64) -> tuple[MediaPreparationExecutor, WorkspaceManager]:
    manager = WorkspaceManager(tmp_path / "jobs")
    executor = MediaPreparationExecutor(manager, runner, MergedOutputVerifier(FakeProber(merged_width)), command_timeout_seconds=5)
    return executor, manager


def test_executor_runs_normalization_then_one_concat_and_cleans_success(tmp_path: Path) -> None:
    """Measured progress follows command order and success leaves no workspace."""

    runner = RecordingRunner()
    executor, manager = _executor(tmp_path, runner)
    events: list[ProgressEvent] = []

    result = executor.execute_preparation(_job(), Path("ffmpeg"), progress=events.append)

    assert result.normalization_count == 2
    assert len(result.process_results) == 3
    assert len(runner.commands) == 3
    assert "normalized" in runner.commands[0][-1]
    assert "normalized" in runner.commands[1][-1]
    assert runner.commands[2][-1].endswith("merged.mkv")
    assert not any(manager.root.iterdir())
    assert [event.stage for event in events if event.completed == event.total] == [PipelineStage.NORMALIZE, PipelineStage.CONCATENATE, PipelineStage.VERIFY, PipelineStage.CLEANUP]


def test_composable_executor_retains_verified_merged_media_for_caller(tmp_path: Path) -> None:
    """A full-job owner can continue using merged media before final cleanup."""

    runner = RecordingRunner()
    executor, manager = _executor(tmp_path, runner)
    workspace = manager.create()
    events: list[ProgressEvent] = []

    result = executor.execute_preparation_in_workspace(_job(), Path("ffmpeg"), workspace, progress=events.append)

    assert result.workspace_identifier == workspace.identifier
    assert result.merged_probe.path == workspace.path / "merged.mkv"
    assert result.merged_probe.path.is_file()
    assert PipelineStage.CLEANUP not in {event.stage for event in events}
    manager.cleanup(workspace)
    assert not workspace.path.exists()


def test_process_failure_retains_workspace_and_stops_before_concat(tmp_path: Path) -> None:
    """A failed normalization retains diagnostics and prevents concat."""

    runner = RecordingRunner(fail_at=2)
    executor, _manager = _executor(tmp_path, runner)

    with pytest.raises(PreparationFailed) as captured:
        executor.execute_preparation(_job(), Path("ffmpeg"))

    assert captured.value.stage is PipelineStage.NORMALIZE
    assert captured.value.workspace_path.is_dir()
    assert (captured.value.workspace_path / ".ai-video-tools-owned").is_file()
    assert captured.value.diagnostic_tail == "synthetic failure"
    assert isinstance(captured.value.__cause__, ProcessExecutionError)
    assert len(runner.commands) == 2


def test_cancellation_cleans_workspace_after_process_termination(tmp_path: Path) -> None:
    """Cancellation is a clean terminal state rather than a retained failure."""

    runner = RecordingRunner(cancel_at=1)
    executor, manager = _executor(tmp_path, runner)

    with pytest.raises(PreparationCancelled, match="workspace cleaned"):
        executor.execute_preparation(_job(), Path("ffmpeg"), CancellationToken())

    assert not any(manager.root.iterdir())


def test_composable_cancellation_leaves_cleanup_to_caller(tmp_path: Path) -> None:
    """A full-job owner retains control of cancellation cleanup boundaries."""

    runner = RecordingRunner(cancel_at=1)
    executor, manager = _executor(tmp_path, runner)
    workspace = manager.create()

    with pytest.raises(PreparationCancelled) as captured:
        executor.execute_preparation_in_workspace(_job(), Path("ffmpeg"), workspace, CancellationToken())

    assert captured.value.workspace_path == workspace.path
    assert workspace.path.is_dir()
    manager.cleanup(workspace)


def test_verification_failure_retains_workspace(tmp_path: Path) -> None:
    """A structurally invalid merged file is retained for diagnosis."""

    runner = RecordingRunner()
    executor, _manager = _executor(tmp_path, runner, merged_width=32)

    with pytest.raises(PreparationFailed) as captured:
        executor.execute_preparation(_job(), Path("ffmpeg"))

    assert captured.value.stage is PipelineStage.VERIFY
    assert captured.value.workspace_path.is_dir()
    assert "dimensions differ" in str(captured.value)


def test_merged_verifier_accepts_rate_rounding_below_one_timestamp_tick(tmp_path: Path) -> None:
    """Matroska rate fractions may differ while representing the same CFR cadence."""

    path = tmp_path / "merged.mkv"
    path.write_bytes(b"media")
    video = VideoStream(0, "ffv1", 64, 36, "yuv420p", Rational(1, 1), Rational(18227, 1139), Rational(18227, 1139), Rational(1, 1000), Decimal("2"), "bt709", "bt709", "bt709", "tv", 0, False)
    merged = MediaProbe(path, Decimal("2"), (video,), (), ())

    class QuantizedProber:
        """Return the retained-job rate representation."""

        def probe(self, _path: Path) -> MediaProbe:
            """Return one deterministic quantized probe."""

            return merged

    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), Path("output.mp4"), True, (_probe(Path("one.mp4")), _probe(Path("two.mp4"))), Rational(16, 1), 3840, 2160, 4, ConcatStrategy.NORMALIZE, None, (), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"))

    result = MergedOutputVerifier(QuantizedProber()).verify(path, job, ConcatStrategy.NORMALIZE)

    assert result is merged


def test_merged_verifier_reports_exact_frame_timing_operands(tmp_path: Path) -> None:
    """A retained preparation failure identifies every rate decision input."""

    path = tmp_path / "merged.mkv"
    path.write_bytes(b"media")
    merged = MediaProbe(path, Decimal("2"), (_video(duration=Decimal("2"), codec="ffv1", rate=Rational(12, 1), time_base=Rational(1, 1000)),), (), ())

    class MismatchedProber:
        """Return a deterministic mismatched rate."""

        def probe(self, _path: Path) -> MediaProbe:
            """Return the prepared mismatch."""

            return merged

    with pytest.raises(MergedOutputVerificationError) as captured:
        MergedOutputVerifier(MismatchedProber()).verify(path, _job(), ConcatStrategy.NORMALIZE)

    message = str(captured.value)
    assert "merged video frame timing mismatch" in message
    assert "expected=10/1" in message
    assert "effective=12/1" in message
    assert "r_frame_rate=12/1" in message
    assert "avg_frame_rate=12/1" in message
    assert "time_base=1/1000" in message
    assert "frame_period_delta=1/60s" in message
    assert "tolerance=<1/1000s" in message
