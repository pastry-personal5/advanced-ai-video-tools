"""Single-worker FIFO scheduling for frontend-independent pipeline jobs."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from loguru import logger

from advanced_ai_video_tools.core.models import JobRequest, JobState, PipelineStage, ProgressEvent
from advanced_ai_video_tools.services.pipeline import PipelineCancelled, PipelineFailed, PipelineResult
from advanced_ai_video_tools.storage.naming import automatic_output_basename, automatic_output_basename_matches
from advanced_ai_video_tools.system.processes import CancellationToken

QueueEventCallback = Callable[["QueueJobSnapshot"], None]


def _local_now() -> datetime:
    return datetime.now().astimezone()


class PipelineRunner(Protocol):
    """The synchronous processing boundary serialized by the queue."""

    def execute_pipeline(self, request: JobRequest, *, cancellation: CancellationToken | None = None, progress: Callable[[ProgressEvent], None] | None = None, state_changed: Callable[[JobState], None] | None = None, job_id: str | None = None) -> PipelineResult:
        """Execute one job to a terminal state."""


class QueueError(RuntimeError):
    """Base error for invalid queue operations."""


class QueueClosedError(QueueError):
    """A new job was submitted after shutdown began."""


class QueueConflictError(QueueError):
    """A queued or active job already claims the requested destination."""


class QueueWorkerFailed(RuntimeError):
    """An unexpected runner exception was isolated without stopping the queue."""


QueueTerminalError = PipelineFailed | PipelineCancelled | QueueWorkerFailed


@dataclass(frozen=True)
class QueueJobSnapshot:
    """Thread-safe observable state for one submitted job."""

    job_id: str
    request: JobRequest
    state: JobState
    queue_position: int | None
    last_progress: ProgressEvent | None
    revision: int


@dataclass(frozen=True)
class QueueJobOutcome:
    """Terminal result retained for frontend retrieval."""

    job_id: str
    state: JobState
    result: PipelineResult | None = None
    error: QueueTerminalError | None = None


@dataclass
class _JobRecord:
    job_id: str
    request: JobRequest
    destination: Path
    token: CancellationToken
    state: JobState = JobState.QUEUED
    last_progress: ProgressEvent | None = None
    outcome: QueueJobOutcome | None = None
    completed: threading.Event = field(default_factory=threading.Event)
    revision: int = 0


class JobQueue:
    """Serialize pipeline execution and retain observable terminal outcomes."""

    def __init__(self, runner: PipelineRunner, *, event_callback: QueueEventCallback | None = None, clock: Callable[[], datetime] = _local_now) -> None:
        self._runner = runner
        self._event_callback = event_callback
        self._clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._records: dict[str, _JobRecord] = {}
        self._pending: deque[str] = deque()
        self._claimed_destinations: set[Path] = set()
        self._active_id: str | None = None
        self._closing = False
        self._worker = threading.Thread(target=self._work, name="advanced-ai-video-tools-job-queue", daemon=False)
        self._worker.start()

    def __enter__(self) -> JobQueue:
        return self

    def __exit__(self, _exception_type: object, _exception: object, _traceback: object) -> None:
        self.shutdown()

    @staticmethod
    def _destination_key(path: Path) -> Path:
        return path.expanduser().resolve(strict=False)

    def _freeze_request(self, request: JobRequest) -> tuple[JobRequest, Path]:
        created_at = request.created_at or self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("queue clock and frozen creation times must be timezone-aware")
        if request.explicit_output_path is not None:
            if request.generated_output_basename is not None:
                raise ValueError("an explicit output cannot have a generated basename")
            frozen = replace(request, created_at=created_at)
            return frozen, request.explicit_output_path
        basename = request.generated_output_basename or automatic_output_basename(created_at)
        if not automatic_output_basename_matches(basename, created_at):
            raise ValueError("generated basename does not match its frozen creation identity")
        base_path = request.output_directory / basename
        if request.generated_output_basename is not None:
            if base_path.exists():
                raise QueueConflictError(f"frozen generated destination is no longer available: {base_path}")
            return replace(request, created_at=created_at), base_path
        candidate = base_path
        counter = 0
        while candidate.exists() or self._destination_key(candidate) in self._claimed_destinations:
            counter += 1
            candidate = base_path.with_name(f"{base_path.stem}-{counter:02d}{base_path.suffix}")
        frozen = replace(request, created_at=created_at, generated_output_basename=candidate.name)
        return frozen, candidate

    def submit(self, request: JobRequest) -> str:
        """Freeze and append one request, returning its stable queue identifier."""

        if not isinstance(request, JobRequest):
            raise TypeError("request must be a JobRequest instance")
        with self._condition:
            if self._closing:
                raise QueueClosedError("the job queue is shutting down")
            frozen, destination = self._freeze_request(request)
            key = self._destination_key(destination)
            if key in self._claimed_destinations:
                raise QueueConflictError(f"destination is already claimed by a queued or active job: {destination}")
            job_id = uuid4().hex
            record = _JobRecord(job_id, frozen, destination, CancellationToken())
            self._records[job_id] = record
            self._pending.append(job_id)
            self._claimed_destinations.add(key)
            snapshot = self._snapshot_locked(record)
            self._condition.notify_all()
        self._emit((snapshot,))
        logger.info("Queued job={} pending_count={}", job_id, snapshot.queue_position + 1 if snapshot.queue_position is not None else 0)
        return job_id

    def snapshots(self) -> tuple[QueueJobSnapshot, ...]:
        """Return active, pending, and terminal records in submission order."""

        with self._condition:
            return tuple(self._snapshot_locked(record) for record in self._records.values())

    def snapshot(self, job_id: str) -> QueueJobSnapshot:
        """Return one current snapshot or raise for an unknown identifier."""

        with self._condition:
            return self._snapshot_locked(self._record_locked(job_id))

    def move(self, job_id: str, position: int) -> None:
        """Move a pending job to a zero-based FIFO position."""

        with self._condition:
            record = self._record_locked(job_id)
            if position < 0 or position >= len(self._pending):
                raise IndexError("queue position is outside the pending job range")
            if record.state is not JobState.QUEUED or job_id not in self._pending:
                raise QueueError("only pending jobs can be reordered")
            self._pending.remove(job_id)
            self._pending.insert(position, job_id)
            for pending_id in self._pending:
                self._records[pending_id].revision += 1
            snapshots = tuple(self._snapshot_locked(self._records[pending_id]) for pending_id in self._pending)
            self._condition.notify_all()
        self._emit(snapshots)

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending job immediately or signal the active pipeline."""

        with self._condition:
            record = self._record_locked(job_id)
            if record.state in {JobState.CANCELLED, JobState.FAILED, JobState.COMPLETED}:
                return False
            if job_id in self._pending:
                self._pending.remove(job_id)
                error = PipelineCancelled("Queued job cancelled before execution.", PipelineStage.VALIDATE)
                self._finish_locked(record, JobState.CANCELLED, error=error)
                for pending_id in self._pending:
                    self._records[pending_id].revision += 1
                snapshots = (self._snapshot_locked(record),) + tuple(self._snapshot_locked(self._records[pending_id]) for pending_id in self._pending)
            else:
                record.token.cancel()
                record.state = JobState.CANCELLING
                record.revision += 1
                snapshots = (self._snapshot_locked(record),)
            self._condition.notify_all()
        self._emit(snapshots)
        return True

    def wait(self, job_id: str, timeout: float | None = None) -> QueueJobOutcome | None:
        """Wait for one terminal outcome, returning None when a timeout expires."""

        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        with self._condition:
            record = self._record_locked(job_id)
            completed = record.completed
        if not completed.wait(timeout):
            return None
        with self._condition:
            outcome = self._record_locked(job_id).outcome
            if outcome is None:
                raise QueueError("completed job has no terminal outcome")
            return outcome

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Wait until no active or pending work remains."""

        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        with self._condition:
            return self._condition.wait_for(lambda: self._active_id is None and not self._pending, timeout)

    def shutdown(self, timeout: float | None = None) -> bool:
        """Cancel all unfinished jobs and wait for the sole worker to exit."""

        if threading.current_thread() is self._worker:
            raise QueueError("the queue worker cannot wait for its own shutdown")
        with self._condition:
            if not self._closing:
                self._closing = True
                snapshots: list[QueueJobSnapshot] = []
                for job_id in tuple(self._pending):
                    record = self._records[job_id]
                    self._pending.remove(job_id)
                    error = PipelineCancelled("Queued job cancelled during queue shutdown.", PipelineStage.VALIDATE)
                    self._finish_locked(record, JobState.CANCELLED, error=error)
                    snapshots.append(self._snapshot_locked(record))
                if self._active_id is not None:
                    active = self._records[self._active_id]
                    active.token.cancel()
                    active.state = JobState.CANCELLING
                    active.revision += 1
                    snapshots.append(self._snapshot_locked(active))
                self._condition.notify_all()
            else:
                snapshots = []
        self._emit(tuple(snapshots))
        self._worker.join(timeout)
        return not self._worker.is_alive()

    def _record_locked(self, job_id: str) -> _JobRecord:
        try:
            return self._records[job_id]
        except KeyError as error:
            raise KeyError(f"unknown queue job: {job_id}") from error

    def _snapshot_locked(self, record: _JobRecord) -> QueueJobSnapshot:
        position = self._pending.index(record.job_id) if record.job_id in self._pending else None
        return QueueJobSnapshot(record.job_id, record.request, record.state, position, record.last_progress, record.revision)

    def _finish_locked(self, record: _JobRecord, state: JobState, *, result: PipelineResult | None = None, error: QueueTerminalError | None = None) -> None:
        record.state = state
        record.outcome = QueueJobOutcome(record.job_id, state, result, error)
        record.revision += 1
        self._claimed_destinations.discard(self._destination_key(record.destination))
        record.completed.set()

    def _pipeline_state(self, record: _JobRecord, state: JobState) -> None:
        with self._condition:
            if record.outcome is not None or state is JobState.QUEUED and record.state is not JobState.QUEUED:
                return
            if record.state is JobState.CANCELLING and state in {JobState.VALIDATING, JobState.RUNNING}:
                return
            record.state = state
            record.revision += 1
            snapshot = self._snapshot_locked(record)
        self._emit((snapshot,))

    def _pipeline_progress(self, record: _JobRecord, progress: ProgressEvent) -> None:
        with self._condition:
            if record.outcome is not None:
                return
            record.last_progress = progress
            record.revision += 1
            snapshot = self._snapshot_locked(record)
        self._emit((snapshot,))

    def _activate_next_locked(self) -> tuple[_JobRecord, tuple[QueueJobSnapshot, ...]]:
        """Move the next pending record to active and update pending positions."""

        job_id = self._pending.popleft()
        record = self._records[job_id]
        self._active_id = job_id
        record.revision += 1
        for pending_id in self._pending:
            self._records[pending_id].revision += 1
        snapshots = (self._snapshot_locked(record),) + tuple(self._snapshot_locked(self._records[pending_id]) for pending_id in self._pending)
        return record, snapshots

    def _run_record(self, record: _JobRecord) -> tuple[JobState, PipelineResult | None, QueueTerminalError | None]:
        """Run one active record and translate every terminal runner outcome."""

        result: PipelineResult | None = None
        error: QueueTerminalError | None = None
        state = JobState.COMPLETED
        try:
            result = self._runner.execute_pipeline(
                record.request,
                cancellation=record.token,
                progress=lambda event: self._pipeline_progress(record, event),
                state_changed=lambda changed: self._pipeline_state(record, changed),
                job_id=record.job_id,
            )
        except PipelineCancelled as caught:
            state = JobState.CANCELLED
            error = caught
        except PipelineFailed as caught:
            state = JobState.FAILED
            error = caught
        except Exception as caught:  # pylint: disable=broad-exception-caught
            state = JobState.FAILED
            error = QueueWorkerFailed(f"Unexpected pipeline failure: {type(caught).__name__}")
            logger.opt(exception=caught).error("Unexpected exception escaped queued pipeline execution")
        return state, result, error

    def _work(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closing or bool(self._pending))
                if self._closing:
                    return
                record, snapshots = self._activate_next_locked()
            self._emit(snapshots)
            state, result, error = self._run_record(record)
            with self._condition:
                self._finish_locked(record, state, result=result, error=error)
                self._active_id = None
                snapshot = self._snapshot_locked(record)
                self._condition.notify_all()
            self._emit((snapshot,))

    def _emit(self, snapshots: tuple[QueueJobSnapshot, ...]) -> None:
        if self._event_callback is None:
            return
        for snapshot in snapshots:
            try:
                self._event_callback(snapshot)
            except Exception as error:  # pylint: disable=broad-exception-caught
                logger.opt(exception=error).error("Queue event callback failed job={}", snapshot.job_id)
