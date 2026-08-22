"""Native window for observing and controlling queued jobs."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QLabel, QListView, QMainWindow, QProgressBar, QPushButton, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget

from ai_video_tools.core.models import JobState
from ai_video_tools.gui.editor import JobEditor
from ai_video_tools.gui.jobs import JobListModel, JobRole
from ai_video_tools.gui.messages import MessageEvent, MessageWidget
from ai_video_tools.gui.preview import SourcePreviewPane
from ai_video_tools.gui.submission import JobSubmissionController
from ai_video_tools.gui.tool_settings import ToolSettingsDialog, ToolSettingsValidator
from ai_video_tools.system.settings import ApplicationSettings, SettingsStore


class MainWindow(QMainWindow):
    """Desktop shell centered on the shared processing queue."""

    def __init__(self, model: JobListModel, settings: ApplicationSettings, log_path: Path | None = None, *, submission: JobSubmissionController | None = None, tool_validator: ToolSettingsValidator | None = None, settings_store: SettingsStore | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__()
        self._model = model
        self._settings = settings
        self._submission = submission
        self._tool_validator = tool_validator
        self._settings_store = settings_store
        self._last_snapshots: dict[str, object] = {}
        self._global_shutdown_recorded = False
        self.setWindowTitle("AI Video Tools")
        self.setMinimumSize(1536, 1024)

        self.editor = JobEditor(settings)
        self.source_preview = SourcePreviewPane()
        edit_menu = self.menuBar().addMenu("Edit")
        self.preferences_action = QAction("Preferences", self)
        self.preferences_action.setObjectName("preferencesAction")
        self.preferences_action.setEnabled(tool_validator is not None and settings_store is not None)
        edit_menu.addAction(self.preferences_action)
        self.job_list = QListView()
        self.job_list.setObjectName("jobList")
        self.job_list.setModel(model)
        self.job_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.job_list.setAlternatingRowColors(True)
        self.job_list.setAccessibleName("Processing jobs")
        self.status_label = QLabel("No jobs have been submitted.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.output_label = QLabel()
        self.output_label.setObjectName("outputLabel")
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.output_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setObjectName("jobProgress")
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(True)
        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.setObjectName("moveUpButton")
        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.setObjectName("moveDownButton")
        self.cancel_button = QPushButton("Cancel Job")
        self.cancel_button.setObjectName("cancelButton")
        log_label = QLabel(f"Diagnostics: {log_path}" if log_path is not None else "Diagnostics log is not configured")
        log_label.setObjectName("logPathLabel")
        log_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        log_label.setWordWrap(True)

        creation_page = QWidget()
        creation_layout = QVBoxLayout(creation_page)
        creation_content = QHBoxLayout()
        creation_content.addWidget(self.editor, 1)
        creation_content.addWidget(self.source_preview)
        creation_layout.addLayout(creation_content, 1)
        monitoring_page = QWidget()
        monitoring_layout = QVBoxLayout(monitoring_page)
        monitoring_layout.addWidget(self.job_list, 1)
        monitoring_layout.addWidget(self.status_label)
        monitoring_layout.addWidget(self.output_label)
        monitoring_layout.addWidget(self.progress)
        controls = QHBoxLayout()
        controls.addWidget(self.move_up_button)
        controls.addWidget(self.move_down_button)
        controls.addStretch(1)
        controls.addWidget(self.cancel_button)
        monitoring_layout.addLayout(controls)
        monitoring_layout.addWidget(log_label)

        self.view_stack = QStackedWidget()
        self.view_stack.setObjectName("mainViewStack")
        self.view_stack.addWidget(creation_page)
        self.view_stack.addWidget(monitoring_page)
        self.navigation_rail = QWidget()
        self.navigation_rail.setObjectName("navigationRail")
        rail_layout = QVBoxLayout(self.navigation_rail)
        self.job_creation_button = self._navigation_button("✎", "Job Creation", "jobCreationButton")
        self.queue_monitoring_button = self._navigation_button("☷", "Queue Monitoring", "queueMonitoringButton")
        rail_layout.addWidget(self.job_creation_button)
        rail_layout.addWidget(self.queue_monitoring_button)
        rail_layout.addStretch(1)
        self.job_creation_button.clicked.connect(lambda: self._switch_view(0))
        self.queue_monitoring_button.clicked.connect(lambda: self._switch_view(1))
        self.job_creation_button.setChecked(True)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.navigation_rail)
        content_layout.addWidget(self.view_stack, 1)

        self.message_widget = MessageWidget()
        self.message_widget.setObjectName("messageWidget")
        self.message_widget.setMinimumHeight(130)
        self.message_tabs = self.message_widget.tabs
        self.global_messages = self.message_widget.global_messages
        self.job_messages = self.message_widget.job_messages
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("mainContentSplitter")
        splitter.addWidget(content)
        splitter.addWidget(self.message_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        self.setCentralWidget(splitter)

        self.job_list.selectionModel().currentChanged.connect(self._selection_changed)
        model.dataChanged.connect(self._model_changed)
        model.rowsInserted.connect(self._rows_inserted)
        model.modelReset.connect(self._refresh_selection)
        model.snapshot_changed.connect(self._queue_snapshot_changed)
        self.cancel_button.clicked.connect(self._cancel_selected)
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        self.preferences_action.triggered.connect(self._open_tool_settings)
        self.editor.inputs.currentRowChanged.connect(self._source_selection_changed)
        self.editor.inputs.model().rowsInserted.connect(lambda *_: self._source_selection_changed(self.editor.inputs.currentRow()))
        self.editor.inputs.model().rowsRemoved.connect(lambda *_: self._source_selection_changed(self.editor.inputs.currentRow()))
        self.source_preview.previous_requested.connect(lambda: self._select_source_relative(-1))
        self.source_preview.next_requested.connect(lambda: self._select_source_relative(1))
        self.source_preview.first_frame_requested.connect(self.source_preview.go_to_first_frame)
        self.source_preview.last_frame_requested.connect(self.source_preview.go_to_last_frame)
        self.source_preview.preview_error.connect(self._append_global)
        self._append_global("Application started.")
        self._append_global("Add clips in order they should be concatenated.")
        if submission is not None:
            self.editor.request_ready.connect(submission.start)
            submission.busy_changed.connect(self.editor.set_busy)
            submission.status_changed.connect(self.editor.set_status)
            submission.status_changed.connect(self._append_global)
            submission.queued.connect(lambda job_id: self._append_job(job_id, "Job queued."))
            submission.queued.connect(self.editor.job_queued)
            submission.settings_changed.connect(self._settings_changed)
            submission.busy_changed.connect(lambda busy: self._append_global("Preflight started." if busy else "Preflight finished."))
        if tool_validator is not None:
            tool_validator.succeeded.connect(lambda *_: self._append_global("External tools validated."))
            tool_validator.failed.connect(lambda _overrides, message: self._append_global(f"External-tool validation failed: {message}"))
        self._refresh_selection()

    @staticmethod
    def _navigation_button(glyph: str, label: str, object_name: str) -> QToolButton:
        """Create one accessible, mutually exclusive view-rail control."""

        button = QToolButton()
        button.setText(glyph)
        button.setObjectName(object_name)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setMinimumSize(64, 64)
        return button

    @Slot(int)
    def _switch_view(self, index: int) -> None:
        """Switch visible presentation surface without changing job state."""

        self.view_stack.setCurrentIndex(index)
        self.job_creation_button.setChecked(index == 0)
        self.queue_monitoring_button.setChecked(index == 1)

    @Slot(int)
    def _source_selection_changed(self, row: int) -> None:
        """Bind preview identity to editor selection only."""

        paths = self.editor.input_paths()
        self.source_preview.set_sources(paths, row)

    def _select_source_relative(self, offset: int) -> None:
        """Navigate source selection without changing concat order."""

        self._select_source_index(self.editor.inputs.currentRow() + offset)

    def _select_source_index(self, row: int) -> None:
        """Select one existing source row and leave the ordered list intact."""

        if 0 <= row < self.editor.inputs.count():
            self.editor.inputs.setCurrentRow(row)

    def _append_global(self, text: str) -> None:
        self.message_widget.append(MessageEvent(text))

    def _append_job(self, job_id: str, text: str) -> None:
        self.message_widget.append(MessageEvent(text, job_id))

    @Slot(object)
    def _queue_snapshot_changed(self, snapshot: object) -> None:
        job_id = getattr(snapshot, "job_id", None)
        if not job_id:
            return
        previous = self._last_snapshots.get(job_id)
        state = getattr(snapshot, "state", None)
        progress = getattr(snapshot, "last_progress", None)
        if previous is None:
            name = snapshot.request.generated_output_basename or snapshot.request.explicit_output_path or "output"
            self._append_job(job_id, f"Job started: {name}." if state is JobState.RUNNING else "Job queued.")
        elif getattr(previous, "state", None) is not state:
            self._append_job(job_id, f"Job {state.value.replace('_', ' ')}.")
        previous_progress = getattr(previous, "last_progress", None)
        if progress is not None and (previous_progress is None or (progress.stage, progress.message) != (previous_progress.stage, previous_progress.message)):
            self._append_job(job_id, f"{progress.stage.value}: {progress.message}")
        if state is JobState.COMPLETED and getattr(previous, "state", None) is not JobState.COMPLETED:
            name = snapshot.request.generated_output_basename or snapshot.request.explicit_output_path or job_id
            self._append_global(f"Job completed: {name}.")
        self._last_snapshots[job_id] = snapshot

    @Slot(QModelIndex, QModelIndex)
    def _selection_changed(self, _current: QModelIndex, _previous: QModelIndex) -> None:
        self._refresh_selection()

    @Slot(QModelIndex, QModelIndex, list)
    def _model_changed(self, _first: QModelIndex, _last: QModelIndex, _roles: list[int]) -> None:
        self._refresh_selection()

    @Slot(QModelIndex, int, int)
    def _rows_inserted(self, _parent: QModelIndex, first: int, _last: int) -> None:
        if not self.job_list.currentIndex().isValid():
            self.job_list.setCurrentIndex(self._model.index(first, 0))
        self._refresh_selection()

    @Slot()
    def _refresh_selection(self) -> None:
        index = self.job_list.currentIndex()
        if not index.isValid():
            self.status_label.setText("No jobs have been submitted.")
            self.output_label.clear()
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.progress.setFormat("No job selected")
            self.cancel_button.setEnabled(False)
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
            self.message_widget.select_job(None)
            return
        message = self._model.data(index, int(JobRole.ERROR)) or self._model.data(index, int(JobRole.MESSAGE))
        self.status_label.setText(str(message))
        self.output_label.setText(f"Output: {self._model.data(index, int(JobRole.OUTPUT_PATH))}")
        completed = int(self._model.data(index, int(JobRole.PROGRESS_COMPLETED)) or 0)
        total = self._model.data(index, int(JobRole.PROGRESS_TOTAL))
        if total is None:
            self.progress.setRange(0, 0)
            self.progress.setFormat(str(self._model.data(index, int(JobRole.STAGE)) or "Working"))
        else:
            self.progress.setRange(0, max(1, int(total)))
            self.progress.setValue(completed)
            self.progress.setFormat(f"{completed}/{total}")
        self.cancel_button.setEnabled(bool(self._model.data(index, int(JobRole.CAN_CANCEL))))
        position = self._model.data(index, int(JobRole.QUEUE_POSITION))
        self.move_up_button.setEnabled(position is not None and int(position) > 0)
        self.move_down_button.setEnabled(position is not None and int(position) + 1 < self._model.pending_count)
        self.message_widget.select_job(str(self._model.data(index, int(JobRole.JOB_ID))))

    @Slot()
    def _cancel_selected(self) -> None:
        self._model.cancel(self.job_list.currentIndex())

    def _move_selected(self, offset: int) -> None:
        self._model.move_pending(self.job_list.currentIndex(), offset)

    @Slot()
    def _open_tool_settings(self) -> None:
        if self._tool_validator is None or self._settings_store is None:
            return
        dialog = ToolSettingsDialog(self._settings, self._tool_validator, self._settings_store, self)
        dialog.settings_saved.connect(self._settings_changed)
        dialog.exec()

    @Slot(object)
    def _settings_changed(self, value: object) -> None:
        if isinstance(value, ApplicationSettings):
            self._settings = value
            self.editor.apply_settings(value)
            if self._submission is not None:
                self._submission.apply_settings(value)
            self._append_global("Application settings updated.")

    def closeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Record session shutdown before Qt releases the window."""
        self.source_preview.shutdown()
        if not self._global_shutdown_recorded:
            self._append_global("Application shutting down.")
            self._global_shutdown_recorded = True
        super().closeEvent(event)  # type: ignore[arg-type]
