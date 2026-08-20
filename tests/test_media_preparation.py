"""Unit tests for preparation orchestration, progress, cleanup, and retention."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ai_video_tools.core.models import ConcatStrategy, JobPlan, MediaProbe, PipelineStage, ProgressEvent, Rational, VideoStream
from ai_video_tools.services.media_preparation import MediaPreparationExecutor, MergedOutputVerifier, PreparationCancelled, PreparationFailed
from ai_video_tools.storage.workspaces import WorkspaceManager
from ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessExecutionError, ProcessResult


def _video(*, width: int = 64, duration: Decimal = Decimal("1"), codec: str = "h264") -> VideoStream:
    return VideoStream(0, codec, width, 36, "yuv420p", Rational(1, 1), Rational(10, 1), Rational(10, 1), Rational(1, 10240), duration, "bt709", "bt709", "bt709", "tv", 0, False)


def _probe(path: Path, *, width: int = 64) -> MediaProbe:
    return MediaProbe(path, Decimal("1"), (_video(width=width),), (), ())


def _job() -> JobPlan:
    probes = (_probe(Path("one.mp4")), _probe(Path("two.mp4"), width=96))
    return JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), Path("output.mp4"), True, probes, Rational(10, 1), 3840, 2160, 4, ConcatStrategy.NORMALIZE, None, ("dimensions differ",), 100, 120)


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

    result = executor.execute(_job(), Path("ffmpeg"), progress=events.append)

    assert result.normalization_count == 2
    assert len(result.process_results) == 3
    assert len(runner.commands) == 3
    assert "normalized" in runner.commands[0][-1]
    assert "normalized" in runner.commands[1][-1]
    assert runner.commands[2][-1].endswith("merged.mkv")
    assert not any(manager.root.iterdir())
    assert [event.stage for event in events if event.completed == event.total] == [PipelineStage.NORMALIZE, PipelineStage.CONCATENATE, PipelineStage.VERIFY, PipelineStage.CLEANUP]


def test_process_failure_retains_workspace_and_stops_before_concat(tmp_path: Path) -> None:
    """A failed normalization retains diagnostics and prevents concat."""

    runner = RecordingRunner(fail_at=2)
    executor, _manager = _executor(tmp_path, runner)

    with pytest.raises(PreparationFailed) as captured:
        executor.execute(_job(), Path("ffmpeg"))

    assert captured.value.stage is PipelineStage.NORMALIZE
    assert captured.value.workspace_path.is_dir()
    assert (captured.value.workspace_path / ".ai-video-tools-owned").is_file()
    assert captured.value.diagnostic_tail == "synthetic failure"
    assert len(runner.commands) == 2


def test_cancellation_cleans_workspace_after_process_termination(tmp_path: Path) -> None:
    """Cancellation is a clean terminal state rather than a retained failure."""

    runner = RecordingRunner(cancel_at=1)
    executor, manager = _executor(tmp_path, runner)

    with pytest.raises(PreparationCancelled, match="workspace cleaned"):
        executor.execute(_job(), Path("ffmpeg"), CancellationToken())

    assert not any(manager.root.iterdir())


def test_verification_failure_retains_workspace(tmp_path: Path) -> None:
    """A structurally invalid merged file is retained for diagnosis."""

    runner = RecordingRunner()
    executor, _manager = _executor(tmp_path, runner, merged_width=32)

    with pytest.raises(PreparationFailed) as captured:
        executor.execute(_job(), Path("ffmpeg"))

    assert captured.value.stage is PipelineStage.VERIFY
    assert captured.value.workspace_path.is_dir()
    assert "dimensions differ" in str(captured.value)
