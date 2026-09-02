"""Tests for full-job orchestration, lifecycle, ownership, and cancellation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from loguru import logger

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, IssueCode, IssueSeverity, JobPlan, JobRequest, JobState, MediaProbe, PipelineStage, PreflightIssue, PreflightReport, ProgressEvent, Rational, ToolInfo, Toolchain, VideoStream
from advanced_ai_video_tools.services.finalization import FinalizationCancelled, FinalizationResult
from advanced_ai_video_tools.services.frame_extraction import FrameExtractionFailed, FrameExtractionResult
from advanced_ai_video_tools.services.media_preparation import PreparationCancelled, PreparationResult
from advanced_ai_video_tools.services.pipeline import InvalidJobStateTransition, JobLifecycle, PipelineCancelled, PipelineFailed, PipelineService
from advanced_ai_video_tools.services.upscaling import UpscalingResult
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessResult
from advanced_ai_video_tools.video.finalization import FinalAudioMode


def _video() -> VideoStream:
    return VideoStream(0, "h264", 64, 36, "yuv420p", Rational(1, 1), Rational(10, 1), Rational(10, 1), Rational(1, 1000), Decimal("1"), "bt709", "bt709", "bt709", "tv", 0, False)


def _report(tmp_path: Path) -> PreflightReport:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    probe = MediaProbe(source, Decimal("1"), (_video(),), (), ())
    output = tmp_path / "output.mp4"
    plan = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), output, True, (probe,), Rational(10, 1), 64, 36, None, ConcatStrategy.STREAM_COPY, None, (), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"))
    tool = ToolInfo(tmp_path / "tool", "fake version")
    return PreflightReport((), plan, Toolchain(tool, tool, tool, tmp_path / "models"))


class RecordingRegistry:
    """Record terminal reservation release."""

    def __init__(self) -> None:
        self.released: list[Path] = []

    def release(self, path: Path) -> None:
        """Record a released path."""

        self.released.append(path)


class FakePreflight:
    """Return one deterministic report and expose its reservation registry."""

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        self.registry = RecordingRegistry()
        self.calls = 0

    def execute_preflight(self, _request: JobRequest, progress: object = None) -> PreflightReport:
        """Record validation and forward measured synthetic progress."""

        self.calls += 1
        if callable(progress):
            progress(ProgressEvent(PipelineStage.VALIDATE, 0, 1, "Validating"))
            progress(ProgressEvent(PipelineStage.VALIDATE, 1, 1, "Validated"))
        return self.report


class FakePreparation:
    """Create one merged-media result or cancel preparation."""

    def __init__(self, calls: list[str], *, cancel: bool = False) -> None:
        self.calls = calls
        self.cancel = cancel

    def execute_preparation_in_workspace(self, job: JobPlan, _ffmpeg: Path, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: object = None, *, context: object = None) -> PreparationResult:
        """Return merged media inside the shared workspace."""

        del progress, context
        self.calls.append("prepare")
        if self.cancel:
            if cancellation is not None:
                cancellation.cancel()
            raise PreparationCancelled("cancelled", workspace.path, PipelineStage.CONCATENATE)
        merged_path = workspace.path / "merged.mkv"
        merged_path.write_bytes(b"merged")
        merged = MediaProbe(merged_path, Decimal("1"), job.probes[0].video_streams, (), ())
        return PreparationResult(merged, 0, (), workspace.identifier)


class FakeExtraction:
    """Create a typed extraction handoff or fail with retained diagnostics."""

    def __init__(self, calls: list[str], *, fail: bool = False) -> None:
        self.calls = calls
        self.fail = fail

    def execute_extraction(self, prepared: PreparationResult, _job: JobPlan, _ffmpeg: Path, *, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: object = None, context: object = None) -> FrameExtractionResult:
        """Return one synthetic frame inventory."""

        del cancellation, progress, context
        self.calls.append("extract")
        if self.fail:
            raise FrameExtractionFailed("synthetic extraction failure", workspace.path, "bounded diagnostic")
        frames = workspace.path / "frames"
        frames.mkdir()
        frame = frames / "frame-000000001.png"
        frame.write_bytes(b"frame")
        process = ProcessResult(("ffmpeg",), 0, "", "")
        return FrameExtractionResult(frames, frames / "frame-%09d.png", 1, 1, 64, 36, prepared.merged_probe.path, process, workspace.identifier)


class FakeUpscaling:
    """Pass the extracted inventory to finalization without AI work."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def execute_upscaling(self, extracted: FrameExtractionResult, _job: JobPlan, _toolchain: Toolchain, *, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: object = None, context: object = None) -> UpscalingResult:
        """Return a skipped-upscale result in the same workspace."""

        del cancellation, progress, context
        self.calls.append("upscale")
        return UpscalingResult(extracted.frames_directory, extracted.frame_pattern, extracted.frame_count, extracted.frame_width, extracted.frame_height, None, True, extracted.audio_source_path, (), workspace.identifier)


class FakeFinalization:
    """Publish a synthetic result and perform the terminal workspace cleanup."""

    def __init__(self, calls: list[str], manager: WorkspaceManager, *, cancel: bool = False) -> None:
        self.calls = calls
        self.manager = manager
        self.cancel = cancel

    def execute_finalization(self, prepared: PreparationResult, _upscaled: UpscalingResult, job: JobPlan, _toolchain: Toolchain, *, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: object = None, context: object = None) -> FinalizationResult:
        """Model finalization's cleanup ownership on success and cancellation."""

        del cancellation, progress, context
        self.calls.append("finalize")
        self.manager.cleanup(workspace)
        if self.cancel:
            raise FinalizationCancelled("cancelled and cleaned", workspace.path, PipelineStage.ENCODE)
        process = ProcessResult(("ffmpeg",), 0, "", "")
        output_probe = MediaProbe(job.output_path, prepared.merged_probe.duration, prepared.merged_probe.video_streams, (), ())
        return FinalizationResult(job.output_path, output_probe, FinalAudioMode.NONE, process, workspace.identifier)


def _service(tmp_path: Path, report: PreflightReport, calls: list[str], *, preparation_cancel: bool = False, extraction_fail: bool = False, finalization_cancel: bool = False) -> tuple[PipelineService, FakePreflight, WorkspaceManager]:
    manager = WorkspaceManager(tmp_path / "jobs")
    preflight = FakePreflight(report)
    service = PipelineService(
        preflight=preflight,
        workspace_manager=manager,
        preparation=FakePreparation(calls, cancel=preparation_cancel),
        extraction=FakeExtraction(calls, fail=extraction_fail),
        upscaling=FakeUpscaling(calls),
        finalization=FakeFinalization(calls, manager, cancel=finalization_cancel),
    )
    return service, preflight, manager


def test_success_runs_each_stage_once_in_order_and_releases_reservation(tmp_path: Path) -> None:
    """A successful job uses one workspace and reaches completed after cleanup."""

    report = _report(tmp_path)
    calls: list[str] = []
    states: list[JobState] = []
    events: list[ProgressEvent] = []
    service, preflight, manager = _service(tmp_path, report, calls)

    result = service.execute_pipeline(JobRequest((tmp_path / "source.mp4",), tmp_path), progress=events.append, state_changed=states.append)

    assert calls == ["prepare", "extract", "upscale", "finalize"]
    assert states == [JobState.QUEUED, JobState.VALIDATING, JobState.RUNNING, JobState.COMPLETED]
    assert result.preflight is report
    assert result.output_path == report.plan.output_path
    assert preflight.registry.released == [report.plan.output_path]
    assert not any(manager.root.iterdir())
    assert [event.stage for event in events] == [PipelineStage.VALIDATE, PipelineStage.VALIDATE]


def test_pipeline_logs_one_stable_job_id_across_stage_contexts(tmp_path: Path) -> None:
    """Operational logs correlate one job without exposing its source paths."""

    report = _report(tmp_path)
    calls: list[str] = []
    service, _preflight, _manager = _service(tmp_path, report, calls)
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="INFO", format="{extra[job_id]}|{extra[stage]}|{message}")
    try:
        service.execute_pipeline(JobRequest((tmp_path / "source.mp4",), tmp_path))
    finally:
        logger.remove(sink_id)

    records = [message.strip().split("|", 2) for message in messages]
    assert len({record[0] for record in records}) == 1
    assert {record[1] for record in records} >= {"queued", "validate", "normalize", "extract", "upscale", "encode"}
    assert str(tmp_path) not in "\n".join(messages)


def test_validation_failure_never_creates_workspace(tmp_path: Path) -> None:
    """Blocking preflight issues fail before processing without a reservation leak."""

    issue = PreflightIssue(IssueSeverity.ERROR, IssueCode.UNSUPPORTED_HDR, "HDR is unsupported")
    report = PreflightReport((issue,), None, None)
    calls: list[str] = []
    states: list[JobState] = []
    service, preflight, manager = _service(tmp_path, report, calls)

    with pytest.raises(PipelineFailed, match="HDR is unsupported") as captured:
        service.execute_pipeline(JobRequest((), tmp_path), state_changed=states.append)

    assert captured.value.stage is PipelineStage.VALIDATE
    assert states == [JobState.QUEUED, JobState.VALIDATING, JobState.FAILED]
    assert not calls
    assert not preflight.registry.released
    assert not manager.root.exists()


def test_processing_failure_retains_workspace_and_releases_reservation(tmp_path: Path) -> None:
    """A failed stage preserves its workspace and bounded diagnostic tail."""

    report = _report(tmp_path)
    calls: list[str] = []
    states: list[JobState] = []
    service, preflight, _manager = _service(tmp_path, report, calls, extraction_fail=True)

    with pytest.raises(PipelineFailed) as captured:
        service.execute_pipeline(JobRequest((tmp_path / "source.mp4",), tmp_path), state_changed=states.append)

    assert calls == ["prepare", "extract"]
    assert captured.value.stage is PipelineStage.EXTRACT
    assert captured.value.diagnostic_tail == "bounded diagnostic"
    assert captured.value.workspace_path is not None and captured.value.workspace_path.is_dir()
    assert states[-1] is JobState.FAILED
    assert preflight.registry.released == [report.plan.output_path]


def test_pre_finalization_cancellation_cleans_workspace_before_terminal_state(tmp_path: Path) -> None:
    """Cancellation in a composable stage is cleaned by the full-job owner."""

    report = _report(tmp_path)
    calls: list[str] = []
    states: list[JobState] = []
    events: list[ProgressEvent] = []
    service, preflight, manager = _service(tmp_path, report, calls, preparation_cancel=True)

    with pytest.raises(PipelineCancelled) as captured:
        service.execute_pipeline(JobRequest((tmp_path / "source.mp4",), tmp_path), progress=events.append, state_changed=states.append)

    assert captured.value.stage is PipelineStage.CONCATENATE
    assert calls == ["prepare"]
    assert states[-2:] == [JobState.CANCELLING, JobState.CANCELLED]
    assert [event.completed for event in events if event.stage is PipelineStage.CLEANUP] == [0, 1]
    assert not any(manager.root.iterdir())
    assert preflight.registry.released == [report.plan.output_path]


def test_finalization_cancellation_is_not_cleaned_twice(tmp_path: Path) -> None:
    """The terminal service remains the sole cleanup owner during finalization."""

    report = _report(tmp_path)
    calls: list[str] = []
    states: list[JobState] = []
    service, _preflight, manager = _service(tmp_path, report, calls, finalization_cancel=True)

    with pytest.raises(PipelineCancelled) as captured:
        service.execute_pipeline(JobRequest((tmp_path / "source.mp4",), tmp_path), state_changed=states.append)

    assert captured.value.stage is PipelineStage.ENCODE
    assert states[-2:] == [JobState.CANCELLING, JobState.CANCELLED]
    assert not any(manager.root.iterdir())


def test_pre_cancelled_job_never_runs_preflight(tmp_path: Path) -> None:
    """Cancellation before validation is an immediate clean terminal state."""

    report = _report(tmp_path)
    calls: list[str] = []
    states: list[JobState] = []
    token = CancellationToken()
    token.cancel()
    service, preflight, manager = _service(tmp_path, report, calls)

    with pytest.raises(PipelineCancelled, match="before validation"):
        service.execute_pipeline(JobRequest((tmp_path / "source.mp4",), tmp_path), cancellation=token, state_changed=states.append)

    assert states == [JobState.QUEUED, JobState.CANCELLING, JobState.CANCELLED]
    assert preflight.calls == 0
    assert not manager.root.exists()


def test_cancellation_during_validation_releases_the_new_reservation(tmp_path: Path) -> None:
    """A request cancelled while preflight runs cannot hold a runnable output path."""

    report = _report(tmp_path)
    calls: list[str] = []
    states: list[JobState] = []
    token = CancellationToken()
    service, preflight, manager = _service(tmp_path, report, calls)

    def cancel_during_validation(state: JobState) -> None:
        states.append(state)
        if state is JobState.VALIDATING:
            token.cancel()

    with pytest.raises(PipelineCancelled, match="after validation"):
        service.execute_pipeline(JobRequest((tmp_path / "source.mp4",), tmp_path), cancellation=token, state_changed=cancel_during_validation)

    assert states == [JobState.QUEUED, JobState.VALIDATING, JobState.CANCELLING, JobState.CANCELLED]
    assert not calls
    assert preflight.registry.released == [report.plan.output_path]
    assert not manager.root.exists()


def test_lifecycle_rejects_invalid_terminal_transition() -> None:
    """Terminal jobs cannot silently return to a runnable state."""

    lifecycle = JobLifecycle()
    lifecycle.transition(JobState.VALIDATING)
    lifecycle.transition(JobState.FAILED)

    with pytest.raises(InvalidJobStateTransition, match="failed to running"):
        lifecycle.transition(JobState.RUNNING)
