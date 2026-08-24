"""Native window for observing and controlling queued jobs."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton, QSplitter, QStackedWidget, QTableView, QToolButton, QVBoxLayout, QWidget

from advanced_ai_video_tools.core.models import JobState, PipelineStage, Toolchain
from advanced_ai_video_tools.gui.editor import JobEditor
from advanced_ai_video_tools.gui.jobs import JobListModel, JobRole
from advanced_ai_video_tools.gui.identity import GUI_DISPLAY_NAME
from advanced_ai_video_tools.gui.messages import MessageEvent, MessageWidget
from advanced_ai_video_tools.gui.preview import SourcePreviewPane
from advanced_ai_video_tools.gui.submission import JobSubmissionController
from advanced_ai_video_tools.gui.theme import CONTROL_RADIUS, MAJOR_REGION_GAP, SPACE_2, SPACE_3, SPACE_4
from advanced_ai_video_tools.gui.tool_settings import ToolSettingsDialog, ToolSettingsValidator
from advanced_ai_video_tools.system.settings import ApplicationSettings, SettingsError, SettingsStore


class MainWindow(QMainWindow):
    """Desktop shell centered on the shared processing queue."""

    def __init__(self, model: JobListModel, settings: ApplicationSettings, log_path: Path | None = None, *, submission: JobSubmissionController | None = None, tool_validator: ToolSettingsValidator | None = None, settings_store: SettingsStore | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__()
        del log_path
        self._model = model
        self._settings = settings
        self._submission = submission
        self._tool_validator = tool_validator
        self._settings_store = settings_store
        self._last_snapshots: dict[str, object] = {}
        self._last_upscale_message_percent: dict[str, int] = {}
        self._preview_processing_job_id: str | None = None
        self._global_shutdown_recorded = False
        self.setWindowTitle(GUI_DISPLAY_NAME)
        self.setMinimumSize(1400, 880)

        self.editor = JobEditor(settings, queued_inputs=self._queued_source_paths)
        self.source_preview = SourcePreviewPane(muted=settings.preview_muted, volume=settings.preview_volume)
        edit_menu = self.menuBar().addMenu("Edit")
        self.preferences_action = QAction("Preferences", self)
        self.preferences_action.setObjectName("preferencesAction")
        self.preferences_action.setEnabled(tool_validator is not None and settings_store is not None)
        edit_menu.addAction(self.preferences_action)
        self.job_list = QTableView()
        self.job_list.setObjectName("jobList")
        self.job_list.setModel(model)
        self.job_list.setFixedHeight(240)
        self.job_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.job_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.job_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.job_list.horizontalHeader().setStretchLastSection(False)
        self.job_list.setColumnWidth(0, 180)
        self.job_list.setColumnWidth(1, 520)
        self.job_list.setColumnWidth(2, 120)
        self.job_list.setAlternatingRowColors(True)
        self.job_list.setAccessibleName("Processing jobs")
        job_queue_group = QGroupBox("Job Queue")
        job_queue_group.setObjectName("jobQueueGroup")
        job_queue_layout = QVBoxLayout(job_queue_group)
        job_queue_layout.setContentsMargins(SPACE_3, SPACE_4, SPACE_3, SPACE_3)
        job_queue_layout.setSpacing(SPACE_2)
        job_queue_layout.addWidget(self.job_list)
        self.status_label = QLabel("No jobs have been submitted.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.output_label = QLabel()
        self.output_label.setObjectName("outputLabel")
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.output_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setObjectName("jobProgress")
        self.progress.setAccessibleName("Stage progress")
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(True)
        self.overall_progress = QProgressBar()
        self.overall_progress.setObjectName("wholeJobProgress")
        self.overall_progress.setAccessibleName("Whole job progress")
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("Whole job: 0%")
        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.setObjectName("moveUpButton")
        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.setObjectName("moveDownButton")
        self.cancel_button = QPushButton("Cancel Job")
        self.cancel_button.setObjectName("cancelButton")
        details = QGroupBox("Selected Job")
        details.setObjectName("selectedJobDetails")
        details_layout = QFormLayout(details)
        details_layout.setContentsMargins(SPACE_3, SPACE_4, SPACE_3, SPACE_3)
        details_layout.setHorizontalSpacing(SPACE_3)
        details_layout.setVerticalSpacing(SPACE_2)
        self.job_name_value = QLabel("No job selected")
        self.job_name_value.setObjectName("selectedJobName")
        self.job_state_value = QLabel("No job selected")
        self.job_state_value.setObjectName("selectedJobStatus")
        self.job_stage_value = QLabel("No job selected")
        self.job_stage_value.setObjectName("selectedJobStage")
        details_layout.addRow("Job Name", self.job_name_value)
        details_layout.addRow("Status", self.job_state_value)
        details_layout.addRow("Stage", self.job_stage_value)
        details_layout.addRow("Message", self.status_label)
        details_layout.addRow("Output", self.output_label)

        creation_page = QWidget()
        creation_layout = QVBoxLayout(creation_page)
        # The rail already owns the horizontal edge inset. Removing a second
        # left inset keeps the visible button-to-panel gap optically symmetric.
        creation_layout.setContentsMargins(0, SPACE_4, SPACE_4, SPACE_4)
        creation_content = QHBoxLayout()
        creation_content.setContentsMargins(0, 0, 0, 0)
        creation_content.setSpacing(MAJOR_REGION_GAP)
        creation_content.addWidget(self.editor, 1)
        creation_content.addWidget(self.source_preview)
        creation_layout.addLayout(creation_content, 1)
        monitoring_page = QWidget()
        monitoring_layout = QVBoxLayout(monitoring_page)
        monitoring_layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)
        monitoring_layout.setSpacing(SPACE_3)
        monitoring_layout.addWidget(job_queue_group, 1)
        monitoring_layout.addWidget(details)
        monitoring_layout.addWidget(self.overall_progress)
        monitoring_layout.addWidget(self.progress)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(SPACE_2)
        controls.addWidget(self.move_up_button)
        controls.addWidget(self.move_down_button)
        controls.addStretch(1)
        controls.addWidget(self.cancel_button)
        monitoring_layout.addLayout(controls)

        self.view_stack = QStackedWidget()
        self.view_stack.setObjectName("mainViewStack")
        self.view_stack.addWidget(creation_page)
        self.view_stack.addWidget(monitoring_page)
        self.navigation_rail = QWidget()
        self.navigation_rail.setObjectName("navigationRail")
        rail_layout = QVBoxLayout(self.navigation_rail)
        rail_layout.setSpacing(SPACE_2)
        self.job_creation_button = self._navigation_button("create", "Job Creation", "jobCreationButton")
        self.queue_monitoring_button = self._navigation_button("queue", "Queue Monitoring", "queueMonitoringButton")
        rail_layout.setContentsMargins(SPACE_2, SPACE_4, SPACE_2, SPACE_4)
        rail_width = self.job_creation_button.minimumWidth() + (SPACE_2 * 2)
        self.navigation_rail.setFixedWidth(rail_width)
        rail_layout.addWidget(self.job_creation_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        rail_layout.addWidget(self.queue_monitoring_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        rail_layout.addStretch(1)
        self.job_creation_button.clicked.connect(lambda: self._switch_view(0))
        self.queue_monitoring_button.clicked.connect(lambda: self._switch_view(1))
        self.job_creation_button.setChecked(True)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.navigation_rail)
        content_layout.addWidget(self.view_stack, 1)

        self.message_widget = MessageWidget()
        self.message_widget.setObjectName("messageWidget")
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
        self.job_list.clicked.connect(self._queue_cell_clicked)
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
        self.source_preview.audio_preferences_changed.connect(self._audio_preferences_changed)
        self.editor.message.connect(self._append_global)
        self._append_global("Application started.")
        self._append_global("Add clips in order they should be concatenated.")
        if submission is not None:
            self.editor.request_ready.connect(submission.start)
            submission.busy_changed.connect(self.editor.set_busy)
            submission.status_changed.connect(self._append_global)
            submission.queued.connect(lambda job_id: self._append_job(job_id, "Job queued."))
            submission.queued.connect(self.editor.job_queued)
            submission.settings_changed.connect(self._settings_changed)
            submission.busy_changed.connect(lambda busy: self._append_global("Preflight started." if busy else "Preflight finished."))
        if tool_validator is not None:
            tool_validator.succeeded.connect(self._tools_validated)
            tool_validator.failed.connect(lambda _overrides, message: self._append_global(f"External-tool validation failed: {message}"))
        self._refresh_selection()

    @staticmethod
    def _navigation_button(glyph: str, label: str, object_name: str) -> QToolButton:
        """Create one accessible, mutually exclusive view-rail control."""

        button = QToolButton()
        icon = QPixmap(18, 18)
        icon.fill(Qt.GlobalColor.transparent)
        painter = QPainter(icon)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#e8eaed"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if glyph == "create":
            painter.drawRoundedRect(3, 2, 10, 14, 1.5, 1.5)
            painter.drawLine(6, 6, 10, 6)
            painter.drawLine(6, 9, 10, 9)
            painter.drawLine(13, 11, 13, 16)
            painter.drawLine(10.5, 13.5, 15.5, 13.5)
        else:
            for y in (3, 8, 13):
                painter.drawLine(3, y, 5, y)
                painter.drawLine(7, y, 15, y)
        painter.end()
        button.setIcon(QIcon(icon))
        button.setIconSize(icon.size())
        button.setText("")
        button.setObjectName(object_name)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setMinimumSize(64, 64)
        button.setFixedSize(64, 64)
        font = QFont(button.font())
        font.setPointSize(max(1, font.pointSize() * 2))
        button.setFont(font)
        button.setStyleSheet("QToolButton { " f"border: 1px solid transparent; border-radius: {CONTROL_RADIUS}px; " "min-width: 62px; max-width: 62px; min-height: 62px; max-height: 62px; " "outline: none; background: #303134; color: #e8eaed; padding: 0px; }" "QToolButton:checked { color: #ffffff; background: #39485f; border-color: #8ab4f8; }" "QToolButton:hover { background: #3c4043; border-color: #8ab4f8; }" "QToolButton:pressed { background: #474a4f; }")
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

    def _queued_source_paths(self) -> tuple[Path, ...]:
        """Return source paths referenced by jobs that still occupy the queue."""

        active_states = {JobState.QUEUED, JobState.VALIDATING, JobState.RUNNING, JobState.CANCELLING}
        paths: list[Path] = []
        for row in range(self._model.rowCount()):
            snapshot = self._model.snapshot_at(self._model.index(row, 0))
            if snapshot is not None and snapshot.state in active_states:
                paths.extend(snapshot.request.inputs)
        return tuple(paths)

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

    @Slot(object, object)
    def _tools_validated(self, _overrides: object, toolchain: object) -> None:
        """Publish resolved tool paths without exposing command lines."""

        if not isinstance(toolchain, Toolchain):
            self._append_global("External tools validated, but no resolved toolchain was returned.")
            return
        self._append_global("External tools validated: " f"FFmpeg {toolchain.ffmpeg.path}; FFprobe {toolchain.ffprobe.path}; " f"Real-ESRGAN {toolchain.realesrgan.path}; models {toolchain.model_directory}.")

    def _append_upscale_progress(self, job_id: str, progress: object) -> None:
        """Append a concise upscale summary at 10-percent intervals."""

        total = getattr(progress, "total", None)
        completed = max(0, int(getattr(progress, "completed", 0)))
        if total is None or int(total) <= 0:
            return
        total = int(total)
        percent = min(100, completed * 100 // total)
        previous_percent = self._last_upscale_message_percent.get(job_id, -10)
        if percent < previous_percent:
            previous_percent = -10
        if percent == 100 or percent >= previous_percent + 10:
            self._append_job(job_id, f"Upscale progress: {percent}% ({completed}/{total} frames).")
            self._last_upscale_message_percent[job_id] = percent

    @Slot(object)
    def _queue_snapshot_changed(self, snapshot: object) -> None:
        job_id = getattr(snapshot, "job_id", None)
        if not job_id:
            return
        previous = self._last_snapshots.get(job_id)
        state = getattr(snapshot, "state", None)
        progress = getattr(snapshot, "last_progress", None)
        previous_state = getattr(previous, "state", None)
        if state is JobState.RUNNING and previous_state is not JobState.RUNNING:
            self.source_preview.pause_for_processing()
            self._preview_processing_job_id = job_id
        elif self._preview_processing_job_id == job_id and state in {JobState.CANCELLED, JobState.FAILED, JobState.COMPLETED}:
            self._preview_processing_job_id = None
        if previous is None:
            name = snapshot.request.generated_output_basename or snapshot.request.explicit_output_path or "output"
            self._append_job(job_id, f"Job started: {name}." if state is JobState.RUNNING else "Job queued.")
        elif previous_state is not state:
            self._append_job(job_id, f"Job {state.value.replace('_', ' ')}.")
        previous_progress = getattr(previous, "last_progress", None)
        if progress is not None and (previous_progress is None or (progress.stage, progress.message) != (previous_progress.stage, previous_progress.message)):
            if progress.stage is PipelineStage.UPSCALE:
                self._append_upscale_progress(job_id, progress)
            else:
                self._append_job(job_id, f"{progress.stage.value}: {progress.message}")
        if state is JobState.COMPLETED and getattr(previous, "state", None) is not JobState.COMPLETED:
            name = snapshot.request.generated_output_basename or snapshot.request.explicit_output_path or job_id
            self._append_global(f"Job completed: {name}.")
        self._last_snapshots[job_id] = snapshot

    @Slot(QModelIndex, QModelIndex)
    def _selection_changed(self, _current: QModelIndex, _previous: QModelIndex) -> None:
        self._refresh_selection(activate_job_tab=True)

    @Slot(QModelIndex)
    def _queue_cell_clicked(self, index: QModelIndex) -> None:
        """Handle the terminal-row Remove action in the queue table."""

        if index.column() == 2:
            self._model.remove(index)

    @Slot(QModelIndex, QModelIndex, list)
    def _model_changed(self, _first: QModelIndex, _last: QModelIndex, _roles: list[int]) -> None:
        self._refresh_selection()

    @Slot(QModelIndex, int, int)
    def _rows_inserted(self, _parent: QModelIndex, first: int, _last: int) -> None:
        if not self.job_list.currentIndex().isValid():
            self.job_list.setCurrentIndex(self._model.index(first, 0))
        self._refresh_selection()

    @Slot()
    def _refresh_selection(self, *, activate_job_tab: bool = False) -> None:
        # Selection binding intentionally updates the complete details surface together.
        # pylint: disable=too-many-statements
        index = self.job_list.currentIndex()
        if not index.isValid():
            self.status_label.setText("No jobs have been submitted.")
            self.output_label.clear()
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.progress.setFormat("Stage: no job selected")
            self.overall_progress.setValue(0)
            self.overall_progress.setFormat("Whole job: 0%")
            self.cancel_button.setEnabled(False)
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
            self.job_name_value.setText("No job selected")
            self.job_state_value.setText("No job selected")
            self.job_stage_value.setText("No job selected")
            self.message_widget.select_job(None)
            return
        message = self._model.data(index, int(JobRole.ERROR)) or self._model.data(index, int(JobRole.MESSAGE))
        self.status_label.setText(str(message))
        self.output_label.setText(str(self._model.data(index, int(JobRole.OUTPUT_PATH))))
        self.job_name_value.setText(str(self._model.data(self._model.index(index.row(), 1), int(Qt.ItemDataRole.DisplayRole))))
        self.job_state_value.setText(str(self._model.data(index, int(JobRole.STATE))).replace("_", " ").title())
        self.job_stage_value.setText(str(self._model.data(index, int(JobRole.STAGE)) or "Waiting"))
        completed = int(self._model.data(index, int(JobRole.PROGRESS_COMPLETED)) or 0)
        total = self._model.data(index, int(JobRole.PROGRESS_TOTAL))
        state = self._model.data(index, int(JobRole.STATE))
        stage = self._model.data(index, int(JobRole.STAGE))
        if state == JobState.COMPLETED.value:
            whole_percent = 100
        elif stage is None:
            whole_percent = 0
        else:
            stage_index = tuple(item.value for item in PipelineStage).index(str(stage))
            stage_fraction = completed / max(1, int(total)) if total is not None else 0.0
            whole_percent = min(99, int(((stage_index + stage_fraction) / len(PipelineStage)) * 100))
        self.overall_progress.setValue(whole_percent)
        self.overall_progress.setFormat(f"Whole job: {whole_percent}%")
        if total is None:
            self.progress.setRange(0, 0)
            self.progress.setFormat(f"Stage: {stage or 'Working'} (measuring…)")
        else:
            self.progress.setRange(0, max(1, int(total)))
            self.progress.setValue(completed)
            self.progress.setFormat(f"Stage: {completed}/{total}")
        self.cancel_button.setEnabled(bool(self._model.data(index, int(JobRole.CAN_CANCEL))))
        position = self._model.data(index, int(JobRole.QUEUE_POSITION))
        self.move_up_button.setEnabled(position is not None and int(position) > 0)
        self.move_down_button.setEnabled(position is not None and int(position) + 1 < self._model.pending_count)
        self.message_widget.select_job(str(self._model.data(index, int(JobRole.JOB_ID))), activate=activate_job_tab)

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
            self.source_preview.set_audio_preferences(value.preview_muted, value.preview_volume)
            if self._submission is not None:
                self._submission.apply_settings(value)
            self._append_global("Application settings updated.")

    @Slot(bool, int)
    def _audio_preferences_changed(self, muted: bool, volume: int) -> None:
        """Persist only non-safety preview audio preferences."""

        updated = replace(self._settings, preview_muted=muted, preview_volume=volume)
        if self._settings_store is not None:
            try:
                self._settings_store.save(updated)
            except SettingsError as error:
                self._append_global(f"Preview audio preferences could not be saved: {error}")
                return
        self._settings = updated

    def closeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Record session shutdown before Qt releases the window."""
        self.source_preview.shutdown()
        if not self._global_shutdown_recorded:
            self._append_global("Application shutting down.")
            self._global_shutdown_recorded = True
        super().closeEvent(event)  # type: ignore[arg-type]
