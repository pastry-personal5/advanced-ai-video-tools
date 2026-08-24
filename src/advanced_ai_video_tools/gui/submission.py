"""GUI preflight review, acknowledgement, queueing, and preference updates."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from loguru import logger
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout, QWidget

from advanced_ai_video_tools.core.models import IssueCode, IssueSeverity, JobRequest, PreflightReport, ProgressEvent
from advanced_ai_video_tools.gui.preflight import GuiPreflightController
from advanced_ai_video_tools.services.queue import JobQueue, QueueError
from advanced_ai_video_tools.system.settings import ApplicationSettings, SettingsError, SettingsStore


@dataclass(frozen=True)
class PreflightDecision:
    """Explicit user response to one diagnostic report."""

    accepted: bool
    acknowledge_dropped_streams: bool = False


DecisionProvider = Callable[[QWidget | None, PreflightReport], PreflightDecision]


class PreflightDialog(QDialog):
    """Show every preflight issue and gate unsupported stream dropping."""

    def __init__(self, report: PreflightReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stream_ack_required = any(issue.severity is IssueSeverity.ERROR and issue.code is IssueCode.STREAM_ACKNOWLEDGEMENT for issue in report.issues)
        unrelated_errors = any(issue.severity is IssueSeverity.ERROR and issue.code is not IssueCode.STREAM_ACKNOWLEDGEMENT for issue in report.issues) or (report.plan is None and not self._stream_ack_required)
        self.setWindowTitle("Preflight review")
        self.setMinimumSize(680, 380)

        heading = QLabel("Preflight found blocking problems." if unrelated_errors else "Review this job before adding it to the queue.")
        heading.setWordWrap(True)
        issues = QListWidget()
        issues.setObjectName("preflightIssues")
        if not report.issues:
            issues.addItem("READY — no warnings")
        else:
            blocking = tuple(issue for issue in report.issues if issue.severity is IssueSeverity.ERROR)
            warnings = tuple(issue for issue in report.issues if issue.severity is IssueSeverity.WARNING)
            for heading_text, grouped in (("Blocking issues", blocking), ("Warnings", warnings)):
                if not grouped:
                    continue
                heading_item = QListWidgetItem(heading_text)
                heading_item.setFlags(Qt.ItemFlag.NoItemFlags)
                font = heading_item.font()
                font.setBold(True)
                heading_item.setFont(font)
                issues.addItem(heading_item)
                for issue in grouped:
                    location = f" — {issue.path}" if issue.path is not None else ""
                    item = QListWidgetItem(f"{issue.severity.value.upper()} [{issue.code.value}] {issue.message}{location}")
                    issues.addItem(item)

        self.acknowledge = QCheckBox("I understand that the listed unsupported secondary streams and chapters will be dropped for this job.")
        self.acknowledge.setObjectName("acknowledgeDroppedStreams")
        self.acknowledge.setVisible(self._stream_ack_required)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.queue_button = buttons.addButton("Queue Job", QDialogButtonBox.ButtonRole.AcceptRole)
        self.queue_button.setObjectName("confirmQueueButton")
        self.queue_button.setEnabled(not unrelated_errors and not self._stream_ack_required)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.acknowledge.toggled.connect(lambda checked: self.queue_button.setEnabled(not unrelated_errors and checked))

        layout = QVBoxLayout()
        layout.addWidget(heading)
        layout.addWidget(issues, 1)
        layout.addWidget(self.acknowledge)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def decision(self) -> PreflightDecision:
        """Execute modally and return the explicit acknowledgement state."""

        accepted = self.exec() == int(QDialog.DialogCode.Accepted)
        return PreflightDecision(accepted, accepted and self._stream_ack_required and self.acknowledge.isChecked())


def show_preflight_dialog(parent: QWidget | None, report: PreflightReport) -> PreflightDecision:
    """Default native decision provider."""

    return PreflightDialog(report, parent).decision()


class JobSubmissionController(QObject):
    """Coordinate preview, review, queue submission, and safe preference saving."""

    status_changed = Signal(str)
    busy_changed = Signal(bool)
    queued = Signal(str)
    settings_changed = Signal(object)

    def __init__(self, queue: JobQueue, preview: GuiPreflightController, settings: ApplicationSettings, settings_store: SettingsStore, *, decision_provider: DecisionProvider = show_preflight_dialog, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._preview = preview
        self._settings = settings
        self._settings_store = settings_store
        self._decision_provider = decision_provider
        self._dialog_parent: QWidget | None = None
        preview.finished.connect(self._preflight_finished)
        preview.failed.connect(self._preflight_failed)
        preview.progress.connect(self._preflight_progress)
        preview.busy_changed.connect(self.busy_changed)

    def set_dialog_parent(self, parent: QWidget) -> None:
        """Set native dialog ownership after the main window is constructed."""

        self._dialog_parent = parent

    @Slot(object)
    def apply_settings(self, value: object) -> None:
        """Adopt persisted preferences for requests submitted in the future."""

        if isinstance(value, ApplicationSettings):
            self._settings = value

    @Slot(object)
    def start(self, value: object) -> None:
        """Begin asynchronous preflight for one frozen request."""

        if not isinstance(value, JobRequest):
            self.status_changed.emit("Could not create a typed processing request.")
            return
        if not self._preview.start(value):
            self.status_changed.emit("A preflight review is already running.")
            return
        self.status_changed.emit("Validating tools and probing input clips…")

    @Slot(object, object)
    def _preflight_finished(self, request_value: object, report_value: object) -> None:
        if not isinstance(request_value, JobRequest) or not isinstance(report_value, PreflightReport):
            self.status_changed.emit("Preflight returned an invalid result.")
            return
        decision = self._decision_provider(self._dialog_parent, report_value)
        if not decision.accepted:
            self.status_changed.emit("Job was not added to the queue.")
            return
        stream_ack_required = any(issue.severity is IssueSeverity.ERROR and issue.code is IssueCode.STREAM_ACKNOWLEDGEMENT for issue in report_value.issues)
        unrelated_errors = any(issue.severity is IssueSeverity.ERROR and issue.code is not IssueCode.STREAM_ACKNOWLEDGEMENT for issue in report_value.issues) or (report_value.plan is None and not stream_ack_required)
        if unrelated_errors:
            self.status_changed.emit("Resolve the blocking preflight errors before queuing.")
            return
        if stream_ack_required and not decision.acknowledge_dropped_streams:
            self.status_changed.emit("Explicit dropped-stream acknowledgement is required.")
            return
        acknowledgement_keys = tuple(issue.acknowledgement_key for issue in report_value.issues if issue.code is IssueCode.STREAM_ACKNOWLEDGEMENT and issue.acknowledgement_key is not None)
        request = replace(request_value, acknowledge_dropped_streams=stream_ack_required, acknowledged_stream_keys=acknowledgement_keys)
        try:
            job_id = self._queue.submit(request)
        except (QueueError, ValueError) as error:
            logger.warning("GUI queue submission rejected: {}", error)
            QMessageBox.warning(self._dialog_parent, "Could not queue job", str(error))
            self.status_changed.emit(f"Could not queue job: {error}")
            return
        self._save_preferences(request)
        self.status_changed.emit(f"Queued {len(request.inputs)} clip{'s' if len(request.inputs) != 1 else ''}.")
        self.queued.emit(job_id)

    @Slot(object, str)
    def _preflight_failed(self, _request: object, message: str) -> None:
        QMessageBox.critical(self._dialog_parent, "Preflight failed", message)
        self.status_changed.emit(message)

    @Slot(object)
    def _preflight_progress(self, value: object) -> None:
        if isinstance(value, ProgressEvent):
            self.status_changed.emit(value.message)

    def _save_preferences(self, request: JobRequest) -> None:
        updated = replace(
            self._settings,
            recent_input_directory=request.inputs[0].parent if request.inputs else self._settings.recent_input_directory,
            recent_output_directory=request.output_directory,
            target_height=request.target_height,
        )
        try:
            self._settings_store.save(updated)
        except SettingsError as error:
            logger.warning("Job queued but GUI preferences could not be saved: {}", error)
            QMessageBox.warning(self._dialog_parent, "Preferences not saved", f"The job was queued, but preferences could not be saved:\n{error}")
            return
        self._settings = updated
        self.settings_changed.emit(updated)
