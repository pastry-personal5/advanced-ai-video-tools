"""Thread-safe Qt list model over immutable job-queue snapshots."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from enum import IntEnum
from pathlib import Path
from typing import Protocol

from loguru import logger
from PySide6.QtCore import QAbstractTableModel, QByteArray, QModelIndex, QObject, QSortFilterProxyModel, Qt, QThread, Signal, Slot

from advanced_ai_video_tools.core.models import JobState
from advanced_ai_video_tools.services.queue import QueueJobOutcome, QueueJobSnapshot


class JobQueueView(Protocol):
    """Minimal queue surface required by the presentation model."""

    def snapshots(self) -> tuple[QueueJobSnapshot, ...]:
        """Return the current queue snapshots."""

    def cancel(self, job_id: str) -> bool:
        """Request cancellation for one job."""

    def move(self, job_id: str, position: int) -> None:
        """Move one pending job."""

    def wait(self, job_id: str, timeout: float | None = None) -> QueueJobOutcome | None:
        """Return a terminal outcome when available."""


class JobRole(IntEnum):
    """Stable custom roles available to widget and future QML views."""

    JOB_ID = int(Qt.ItemDataRole.UserRole) + 1
    STATE = JOB_ID + 1
    QUEUE_POSITION = JOB_ID + 2
    STAGE = JOB_ID + 3
    PROGRESS_COMPLETED = JOB_ID + 4
    PROGRESS_TOTAL = JOB_ID + 5
    MESSAGE = JOB_ID + 6
    OUTPUT_PATH = JOB_ID + 7
    CAN_CANCEL = JOB_ID + 8
    ERROR = JOB_ID + 9


_TERMINAL_STATES = frozenset({JobState.CANCELLED, JobState.FAILED, JobState.COMPLETED})


class QueueRegionProxyModel(QSortFilterProxyModel):
    """Filter the authoritative queue model into one presentation region."""

    _ACTIVE_STATES = frozenset({JobState.VALIDATING, JobState.RUNNING, JobState.CANCELLING})

    def __init__(self, region: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._region = region
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # pylint: disable=invalid-name
        """Return whether one source snapshot belongs to this region."""

        source = self.sourceModel()
        if source is None:
            return False
        state = source.data(source.index(source_row, 0, source_parent), int(JobRole.STATE))
        try:
            state_value = JobState(str(state))
        except ValueError:
            return False
        if self._region == "active":
            return state_value in self._ACTIVE_STATES
        if self._region == "up_next":
            return state_value is JobState.QUEUED
        if self._region == "history":
            return state_value in _TERMINAL_STATES
        return False

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object | None:  # pylint: disable=invalid-name
        """Give each region's action column the appropriate accessible label."""

        if orientation is Qt.Orientation.Horizontal:
            if role == int(Qt.ItemDataRole.TextAlignmentRole):
                return Qt.AlignmentFlag.AlignCenter
            if role == int(Qt.ItemDataRole.DisplayRole) and section == 2:
                return "Cancel" if self._region == "active" else "Remove"
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object | None:  # pylint: disable=invalid-name
        """Expose region-specific action names while retaining source roles."""

        if index.isValid() and index.column() == 2:
            if role == int(Qt.ItemDataRole.DisplayRole):
                return "Cancel" if self._region == "active" else "Remove"
            if role == int(Qt.ItemDataRole.ToolTipRole):
                return "Cancel this job" if self._region == "active" else "Remove this job"
        return super().data(index, role)


class QueueSnapshotBridge(QObject):
    """Marshal queue callbacks from arbitrary threads onto the Qt event loop."""

    snapshot_received = Signal(object)

    def forward(self, snapshot: QueueJobSnapshot) -> None:
        """Emit one immutable snapshot; Qt performs the cross-thread delivery."""

        self.snapshot_received.emit(snapshot)


class JobListModel(QAbstractTableModel):
    """Observable queue state with all mutations confined to the Qt thread."""

    # Qt's virtual method names are fixed by its public API.
    # pylint: disable=invalid-name

    snapshot_changed = Signal(object)

    def __init__(self, queue: JobQueueView, bridge: QueueSnapshotBridge, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._snapshots: dict[str, QueueJobSnapshot] = {}
        self._order: list[str] = []
        self._submission_order: dict[str, int] = {}
        bridge.snapshot_received.connect(self._apply_snapshot, Qt.ConnectionType.QueuedConnection)
        for snapshot in queue.snapshots():
            self._store_initial(snapshot)

    def roleNames(self) -> dict[int, QByteArray]:
        """Return stable byte names for every custom model role."""

        return {
            int(JobRole.JOB_ID): QByteArray(b"jobId"),
            int(JobRole.STATE): QByteArray(b"state"),
            int(JobRole.QUEUE_POSITION): QByteArray(b"queuePosition"),
            int(JobRole.STAGE): QByteArray(b"stage"),
            int(JobRole.PROGRESS_COMPLETED): QByteArray(b"progressCompleted"),
            int(JobRole.PROGRESS_TOTAL): QByteArray(b"progressTotal"),
            int(JobRole.MESSAGE): QByteArray(b"message"),
            int(JobRole.OUTPUT_PATH): QByteArray(b"outputPath"),
            int(JobRole.CAN_CANCEL): QByteArray(b"canCancel"),
            int(JobRole.ERROR): QByteArray(b"error"),
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the flat number of observed queue records."""

        return 0 if parent.isValid() else len(self._order)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the queue table's Status, Job Name, and Remove columns."""

        return 0 if parent.isValid() else 3

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object | None:
        """Return accessible textual queue column headers."""

        if orientation is Qt.Orientation.Horizontal:
            if role == int(Qt.ItemDataRole.TextAlignmentRole):
                return Qt.AlignmentFlag.AlignCenter
            if role == int(Qt.ItemDataRole.DisplayRole):
                return ("Status", "Job Name", "Remove")[section] if 0 <= section < 3 else None
        return None

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object | None:
        """Resolve display and typed queue data for one row."""

        # A role-oriented Qt model is clearest as one explicit branch per role.
        # pylint: disable=too-many-branches,too-many-return-statements
        snapshot = self.snapshot_at(index)
        if snapshot is None:
            return None
        progress = snapshot.last_progress
        job_name = snapshot.request.generated_output_basename or (snapshot.request.inputs[0].name if snapshot.request.inputs else "Untitled job")
        state_text = snapshot.state.value.replace("_", " ").title()
        if role == int(Qt.ItemDataRole.AccessibleTextRole):
            return f"Status: {state_text}; Job Name: {job_name}"
        if role == int(Qt.ItemDataRole.ToolTipRole):
            if index.column() == 0:
                return f"Job status: {state_text}"
            if index.column() == 1:
                return f"Job name: {job_name}"
            if index.column() == 2:
                if snapshot.state in {JobState.QUEUED, JobState.VALIDATING, JobState.RUNNING}:
                    return "Cancel this job"
                if snapshot.state in _TERMINAL_STATES:
                    return "Remove this job from session history"
            return None
        if role == int(Qt.ItemDataRole.DisplayRole):
            if index.column() == 0:
                return state_text
            if index.column() == 1:
                return job_name
            if index.column() == 2:
                if snapshot.state in {JobState.QUEUED, JobState.VALIDATING, JobState.RUNNING}:
                    return "Cancel"
                return "Remove" if snapshot.state in _TERMINAL_STATES else ""
        if role == int(JobRole.JOB_ID):
            return snapshot.job_id
        if role == int(JobRole.STATE):
            return snapshot.state.value
        if role == int(JobRole.QUEUE_POSITION):
            return snapshot.queue_position
        if role == int(JobRole.STAGE):
            return progress.stage.value if progress is not None else None
        if role == int(JobRole.PROGRESS_COMPLETED):
            return progress.completed if progress is not None else 0
        if role == int(JobRole.PROGRESS_TOTAL):
            return progress.total if progress is not None else None
        if role == int(JobRole.MESSAGE):
            if snapshot.state in _TERMINAL_STATES or snapshot.state is JobState.CANCELLING:
                return self._state_message(snapshot.state)
            return progress.message if progress is not None else self._state_message(snapshot.state)
        if role == int(JobRole.OUTPUT_PATH):
            return str(self._output_path(snapshot))
        if role == int(JobRole.CAN_CANCEL):
            return snapshot.state in {JobState.QUEUED, JobState.VALIDATING, JobState.RUNNING}
        if role == int(JobRole.ERROR):
            outcome = self._queue.wait(snapshot.job_id, timeout=0) if snapshot.state in _TERMINAL_STATES else None
            return str(outcome.error) if outcome is not None and outcome.error is not None else None
        return None

    def snapshot_at(self, index: QModelIndex) -> QueueJobSnapshot | None:
        """Return the typed record at a valid model index."""

        if not index.isValid() or index.row() < 0 or index.row() >= len(self._order):
            return None
        return self._snapshots[self._order[index.row()]]

    def snapshot_for_job(self, job_id: str) -> QueueJobSnapshot | None:
        """Return an observed immutable snapshot by its stable job ID."""

        return self._snapshots.get(job_id)

    def cancel(self, index: QModelIndex) -> bool:
        """Request cancellation for the selected cancellable record."""

        snapshot = self.snapshot_at(index)
        return self._queue.cancel(snapshot.job_id) if snapshot is not None else False

    def remove(self, index: QModelIndex) -> bool:
        """Remove a failed or cancelled row from session presentation history."""

        snapshot = self.snapshot_at(index)
        if snapshot is None or snapshot.state not in _TERMINAL_STATES:
            return False
        row = index.row()
        self.beginRemoveRows(QModelIndex(), row, row)
        self._snapshots.pop(snapshot.job_id, None)
        self._order.pop(row)
        self.endRemoveRows()
        return True

    def move_pending(self, index: QModelIndex, offset: int) -> bool:
        """Move a selected pending record one or more queue positions."""

        snapshot = self.snapshot_at(index)
        if snapshot is None or snapshot.queue_position is None:
            return False
        destination = snapshot.queue_position + offset
        if destination < 0 or destination >= self.pending_count:
            return False
        self._queue.move(snapshot.job_id, destination)
        return True

    @property
    def pending_count(self) -> int:
        """Return the number of records still in the pending FIFO."""

        return sum(snapshot.queue_position is not None for snapshot in self._snapshots.values())

    def _insert_snapshot(self, snapshot: QueueJobSnapshot) -> None:
        """Insert a newly observed queue record at the end of session history."""

        self.beginInsertRows(QModelIndex(), len(self._order), len(self._order))
        self._submission_order[snapshot.job_id] = len(self._submission_order)
        self._snapshots[snapshot.job_id] = snapshot
        self._order.append(snapshot.job_id)
        self.endInsertRows()

    def _refresh_snapshot(self, snapshot: QueueJobSnapshot) -> None:
        """Replace one observed record without changing model ordering."""

        self._snapshots[snapshot.job_id] = snapshot

    @Slot(object)
    def _apply_snapshot(self, value: object) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("job model mutation arrived outside the Qt thread")
        if not isinstance(value, QueueJobSnapshot):
            logger.error("Ignored an invalid queue snapshot type={}", type(value).__name__)
            return
        is_new = value.job_id not in self._snapshots
        if not is_new and value.revision < self._snapshots[value.job_id].revision:
            return
        if is_new:
            self._insert_snapshot(value)
        else:
            self._refresh_snapshot(value)
        desired = self._desired_order()
        if desired != self._order:
            self.beginResetModel()
            self._order = desired
            self.endResetModel()
            self.snapshot_changed.emit(value)
            return
        row = self._order.index(value.job_id)
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1), list(self.roleNames()))
        self.snapshot_changed.emit(value)

    def _store_initial(self, snapshot: QueueJobSnapshot) -> None:
        self._submission_order[snapshot.job_id] = len(self._submission_order)
        self._snapshots[snapshot.job_id] = snapshot
        self._order.append(snapshot.job_id)
        self._order = self._desired_order()

    def _desired_order(self) -> list[str]:
        def sort_key(job_id: str) -> tuple[int, int]:
            snapshot = self._snapshots[job_id]
            if snapshot.queue_position is not None:
                return 1, snapshot.queue_position
            if snapshot.state not in _TERMINAL_STATES:
                return 0, self._submission_order[job_id]
            return 2, self._submission_order[job_id]

        return sorted(self._snapshots, key=sort_key)

    @staticmethod
    def _output_path(snapshot: QueueJobSnapshot) -> Path:
        request = snapshot.request
        if request.explicit_output_path is not None:
            return request.explicit_output_path
        return request.output_directory / (request.generated_output_basename or "")

    @staticmethod
    def _state_message(state: JobState) -> str:
        messages = {
            JobState.QUEUED: "Waiting to start",
            JobState.VALIDATING: "Validating inputs and tools",
            JobState.RUNNING: "Processing",
            JobState.CANCELLING: "Cancelling and cleaning up",
            JobState.CANCELLED: "Cancelled",
            JobState.FAILED: "Failed",
            JobState.COMPLETED: "Completed",
        }
        return messages[state]
