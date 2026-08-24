"""Deterministic tests for serialized FIFO job scheduling and cancellation."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from queue import Queue

import pytest

from advanced_ai_video_tools.core.models import JobRequest, JobState, MediaProbe, PipelineStage, PreflightReport, ProgressEvent
from advanced_ai_video_tools.services.finalization import FinalizationResult
from advanced_ai_video_tools.services.pipeline import PipelineCancelled, PipelineResult
from advanced_ai_video_tools.services.queue import JobQueue, QueueClosedError, QueueConflictError, QueueError, QueueWorkerFailed
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessResult
from advanced_ai_video_tools.video.finalization import FinalAudioMode

_CREATED_AT = datetime(2026, 8, 21, 14, 30, 52, 123456, tzinfo=timezone.utc)


def _request(tmp_path: Path, name: str, *, destination: Path | None = None) -> JobRequest:
    return JobRequest((tmp_path / f"{name}.mov",), tmp_path, explicit_output_path=destination)


def _result(request: JobRequest) -> PipelineResult:
    output = request.explicit_output_path or request.output_directory / str(request.generated_output_basename)
    probe = MediaProbe(output, Decimal("1"), (), (), ())
    finalization = FinalizationResult(output, probe, FinalAudioMode.NONE, ProcessResult(("fake",), 0, "", ""), "fake-workspace")
    return PipelineResult(PreflightReport((), None, None), finalization)


class ControlledRunner:
    """Block each named job until released while observing concurrency."""

    def __init__(self, *, failures: frozenset[str] = frozenset()) -> None:
        self.started: Queue[str] = Queue()
        self.releases: dict[str, threading.Event] = {}
        self.execution_order: list[str] = []
        self.job_ids: list[str] = []
        self.failures = failures
        self.maximum_active = 0
        self._active = 0
        self._lock = threading.Lock()

    @staticmethod
    def _name(request: JobRequest) -> str:
        return request.inputs[0].stem

    def release(self, name: str) -> None:
        """Allow a named running job to finish."""

        self.releases.setdefault(name, threading.Event()).set()

    def run(self, request: JobRequest, *, cancellation: CancellationToken | None = None, progress: object = None, state_changed: object = None, job_id: str | None = None) -> PipelineResult:
        """Model a cooperative synchronous pipeline."""

        assert cancellation is not None
        assert job_id is not None
        name = self._name(request)
        gate = self.releases.setdefault(name, threading.Event())
        with self._lock:
            self._active += 1
            self.maximum_active = max(self.maximum_active, self._active)
            self.execution_order.append(name)
            self.job_ids.append(job_id)
        try:
            if callable(state_changed):
                state_changed(JobState.QUEUED)
                state_changed(JobState.VALIDATING)
                state_changed(JobState.RUNNING)
            if callable(progress):
                progress(ProgressEvent(PipelineStage.VALIDATE, 1, 1, f"Started {name}"))
            self.started.put(name)
            while not gate.is_set():
                if cancellation.wait(0.01):
                    if callable(state_changed):
                        state_changed(JobState.CANCELLING)
                        state_changed(JobState.CANCELLED)
                    raise PipelineCancelled(f"Cancelled {name}", PipelineStage.VALIDATE)
            if cancellation.cancelled:
                if callable(state_changed):
                    state_changed(JobState.CANCELLING)
                    state_changed(JobState.CANCELLED)
                raise PipelineCancelled(f"Cancelled {name}", PipelineStage.VALIDATE)
            if name in self.failures:
                raise RuntimeError(f"unexpected failure in {name}")
            if callable(state_changed):
                state_changed(JobState.COMPLETED)
            return _result(request)
        finally:
            with self._lock:
                self._active -= 1


def test_fifo_runs_exactly_one_job_at_a_time(tmp_path: Path) -> None:
    """Pending work starts in submission order only after cleanup completes."""

    runner = ControlledRunner()
    with JobQueue(runner, clock=lambda: _CREATED_AT) as jobs:
        identifiers = [jobs.submit(_request(tmp_path, name)) for name in ("first", "second", "third")]

        assert runner.started.get(timeout=1) == "first"
        assert jobs.wait(identifiers[1], timeout=0.01) is None
        runner.release("first")
        assert runner.started.get(timeout=1) == "second"
        runner.release("second")
        assert runner.started.get(timeout=1) == "third"
        runner.release("third")

        assert jobs.wait_until_idle(timeout=1)
        assert [jobs.wait(identifier, timeout=0).state for identifier in identifiers] == [JobState.COMPLETED] * 3
        assert runner.execution_order == ["first", "second", "third"]
        assert runner.maximum_active == 1
        assert runner.job_ids == identifiers


def test_pending_jobs_can_be_reordered_without_interrupting_active_work(tmp_path: Path) -> None:
    """A zero-based move changes only the pending FIFO order."""

    runner = ControlledRunner()
    with JobQueue(runner, clock=lambda: _CREATED_AT) as jobs:
        first = jobs.submit(_request(tmp_path, "first"))
        assert runner.started.get(timeout=1) == "first"
        second = jobs.submit(_request(tmp_path, "second"))
        third = jobs.submit(_request(tmp_path, "third"))

        jobs.move(third, 0)
        assert jobs.snapshot(third).queue_position == 0
        assert jobs.snapshot(second).queue_position == 1
        with pytest.raises(QueueError, match="pending"):
            jobs.move(first, 0)

        runner.release("first")
        assert runner.started.get(timeout=1) == "third"
        runner.release("third")
        assert runner.started.get(timeout=1) == "second"
        runner.release("second")
        assert jobs.wait_until_idle(timeout=1)
        assert runner.execution_order == ["first", "third", "second"]


def test_queued_cancellation_never_invokes_pipeline(tmp_path: Path) -> None:
    """Removing pending work produces a typed cancelled outcome immediately."""

    runner = ControlledRunner()
    with JobQueue(runner, clock=lambda: _CREATED_AT) as jobs:
        first = jobs.submit(_request(tmp_path, "first"))
        assert runner.started.get(timeout=1) == "first"
        second = jobs.submit(_request(tmp_path, "second"))

        assert jobs.cancel(second)
        outcome = jobs.wait(second, timeout=0)
        assert outcome is not None and outcome.state is JobState.CANCELLED
        assert isinstance(outcome.error, PipelineCancelled)
        assert not jobs.cancel(second)
        runner.release("first")
        assert jobs.wait(first, timeout=1).state is JobState.COMPLETED
        assert runner.execution_order == ["first"]


def test_active_cancellation_reaches_terminal_before_next_job_starts(tmp_path: Path) -> None:
    """The worker never overlaps a successor with cooperative cancellation cleanup."""

    runner = ControlledRunner()
    with JobQueue(runner, clock=lambda: _CREATED_AT) as jobs:
        first = jobs.submit(_request(tmp_path, "first"))
        assert runner.started.get(timeout=1) == "first"
        second = jobs.submit(_request(tmp_path, "second"))

        assert jobs.cancel(first)
        assert jobs.snapshot(first).state is JobState.CANCELLING
        first_outcome = jobs.wait(first, timeout=1)
        assert first_outcome is not None and first_outcome.state is JobState.CANCELLED
        assert runner.started.get(timeout=1) == "second"
        runner.release("second")
        assert jobs.wait(second, timeout=1).state is JobState.COMPLETED
        assert runner.maximum_active == 1


def test_queue_freezes_names_and_claims_destinations_at_submission(tmp_path: Path) -> None:
    """Queued names do not depend on start time and explicit conflicts fail early."""

    runner = ControlledRunner()
    destination = tmp_path / "shared.mp4"
    with JobQueue(runner, clock=lambda: _CREATED_AT) as jobs:
        generated = jobs.submit(_request(tmp_path, "generated"))
        frozen = jobs.snapshot(generated).request
        assert frozen.created_at == _CREATED_AT
        assert frozen.generated_output_basename is not None
        assert frozen.generated_output_basename.startswith("ai-video-20260821-143052-")
        assert runner.started.get(timeout=1) == "generated"

        explicit = jobs.submit(_request(tmp_path, "explicit", destination=destination))
        with pytest.raises(QueueConflictError, match="already claimed"):
            jobs.submit(_request(tmp_path, "conflict", destination=destination))

        runner.release("generated")
        assert runner.started.get(timeout=1) == "explicit"
        runner.release("explicit")
        assert jobs.wait(explicit, timeout=1).state is JobState.COMPLETED

        reusable = jobs.submit(_request(tmp_path, "reusable", destination=destination))
        assert runner.started.get(timeout=1) == "reusable"
        runner.release("reusable")
        assert jobs.wait(reusable, timeout=1).state is JobState.COMPLETED


def test_shutdown_cancels_active_and_pending_then_rejects_submission(tmp_path: Path) -> None:
    """Application shutdown cannot leave background media work running."""

    runner = ControlledRunner()
    jobs = JobQueue(runner, clock=lambda: _CREATED_AT)
    active = jobs.submit(_request(tmp_path, "active"))
    assert runner.started.get(timeout=1) == "active"
    pending = jobs.submit(_request(tmp_path, "pending"))

    assert jobs.shutdown(timeout=1)
    assert jobs.wait(active, timeout=0).state is JobState.CANCELLED
    assert jobs.wait(pending, timeout=0).state is JobState.CANCELLED
    with pytest.raises(QueueClosedError, match="shutting down"):
        jobs.submit(_request(tmp_path, "late"))


def test_unexpected_failure_is_typed_and_does_not_stop_worker(tmp_path: Path) -> None:
    """One buggy runner call fails its job while later FIFO work still executes."""

    runner = ControlledRunner(failures=frozenset({"broken"}))
    with JobQueue(runner, clock=lambda: _CREATED_AT) as jobs:
        broken = jobs.submit(_request(tmp_path, "broken"))
        healthy = jobs.submit(_request(tmp_path, "healthy"))
        assert runner.started.get(timeout=1) == "broken"
        runner.release("broken")

        broken_outcome = jobs.wait(broken, timeout=1)
        assert broken_outcome is not None and broken_outcome.state is JobState.FAILED
        assert isinstance(broken_outcome.error, QueueWorkerFailed)
        assert runner.started.get(timeout=1) == "healthy"
        runner.release("healthy")
        assert jobs.wait(healthy, timeout=1).state is JobState.COMPLETED


def test_progress_snapshots_are_observable_and_callback_failures_are_isolated(tmp_path: Path) -> None:
    """Frontend notification bugs cannot terminate processing."""

    runner = ControlledRunner()
    callback_calls = 0

    def failing_callback(_snapshot: object) -> None:
        nonlocal callback_calls
        callback_calls += 1
        raise RuntimeError("synthetic frontend callback failure")

    with JobQueue(runner, event_callback=failing_callback, clock=lambda: _CREATED_AT) as jobs:
        identifier = jobs.submit(_request(tmp_path, "progress"))
        assert runner.started.get(timeout=1) == "progress"
        progress = jobs.snapshot(identifier).last_progress
        assert progress is not None and progress.message == "Started progress"
        runner.release("progress")
        assert jobs.wait(identifier, timeout=1).state is JobState.COMPLETED
        assert callback_calls >= 1
