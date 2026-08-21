"""Minimal native window for observing and controlling queued jobs."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QLabel, QListView, QMainWindow, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ai_video_tools.gui.editor import JobEditor
from ai_video_tools.gui.jobs import JobListModel, JobRole
from ai_video_tools.gui.submission import JobSubmissionController
from ai_video_tools.gui.tool_settings import ToolSettingsDialog, ToolSettingsValidator
from ai_video_tools.system.settings import ApplicationSettings, SettingsStore


class MainWindow(QMainWindow):
    """Initial desktop shell centered on the shared processing queue."""

    def __init__(self, model: JobListModel, settings: ApplicationSettings, log_path: Path | None = None, *, submission: JobSubmissionController | None = None, tool_validator: ToolSettingsValidator | None = None, settings_store: SettingsStore | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__()
        self._model = model
        self._settings = settings
        self._submission = submission
        self._tool_validator = tool_validator
        self._settings_store = settings_store
        self.setWindowTitle("AI Video Tools")
        self.setMinimumSize(880, 760)

        self.editor = JobEditor(settings)

        title = QLabel("Video processing jobs")
        title.setObjectName("titleLabel")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        self.subtitle = QLabel(f"One job runs at a time • Default output height: {settings.target_height}p")
        self.subtitle.setObjectName("subtitleLabel")
        self.settings_button = QPushButton("External Tools…")
        self.settings_button.setObjectName("externalToolsButton")
        self.settings_button.setEnabled(tool_validator is not None and settings_store is not None)
        heading_row = QHBoxLayout()
        heading_row.addWidget(self.subtitle, 1)
        heading_row.addWidget(self.settings_button)

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
        self.progress.setValue(0)
        self.progress.setTextVisible(True)

        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.setObjectName("moveUpButton")
        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.setObjectName("moveDownButton")
        self.cancel_button = QPushButton("Cancel Job")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setDefault(False)

        controls = QHBoxLayout()
        controls.addWidget(self.move_up_button)
        controls.addWidget(self.move_down_button)
        controls.addStretch(1)
        controls.addWidget(self.cancel_button)

        log_label = QLabel(f"Diagnostics: {log_path}" if log_path is not None else "Diagnostics log is not configured")
        log_label.setObjectName("logPathLabel")
        log_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        log_label.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addLayout(heading_row)
        layout.addWidget(self.editor)
        layout.addWidget(self.job_list, 1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.output_label)
        layout.addWidget(self.progress)
        layout.addLayout(controls)
        layout.addWidget(log_label)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.job_list.selectionModel().currentChanged.connect(self._selection_changed)
        model.dataChanged.connect(self._model_changed)
        model.rowsInserted.connect(self._rows_inserted)
        model.modelReset.connect(self._refresh_selection)
        self.cancel_button.clicked.connect(self._cancel_selected)
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        self.settings_button.clicked.connect(self._open_tool_settings)
        if submission is not None:
            self.editor.request_ready.connect(submission.start)
            submission.busy_changed.connect(self.editor.set_busy)
            submission.status_changed.connect(self.editor.set_status)
            submission.settings_changed.connect(self._apply_settings)
            submission.queued.connect(self.editor.job_queued)
        self._refresh_selection()

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
        dialog.settings_saved.connect(self._apply_settings)
        dialog.exec()

    @Slot(object)
    def _apply_settings(self, value: object) -> None:
        """Synchronize persisted preferences across future request creators."""

        if not isinstance(value, ApplicationSettings):
            return
        self._settings = value
        self.subtitle.setText(f"One job runs at a time • Default output height: {value.target_height}p")
        self.editor.apply_settings(value)
        if self._submission is not None:
            self._submission.apply_settings(value)
