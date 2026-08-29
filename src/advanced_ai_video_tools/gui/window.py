"""Native window for observing and controlling queued jobs."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QProgressBar, QPushButton, QSplitter, QStackedWidget, QTableView, QToolButton, QVBoxLayout, QWidget

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
        self.queue_table = QTableView()
        self.queue_table.setObjectName("queueTable")
        self.queue_table.setModel(model)
        self.queue_table.setFixedHeight(240)
        self.queue_table.setContentsMargins(0, 0, 0, 0)
        self.queue_table.setShowGrid(False)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.verticalHeader().setDefaultSectionSize(40)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 140)
        header.resizeSection(2, 110)
        header.setStretchLastSection(False)
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setAccessibleName("Processing queue")
        job_queue_group = QGroupBox("Job Queue")
        job_queue_group.setObjectName("queueGroup")
        job_queue_layout = QVBoxLayout(job_queue_group)
        job_queue_layout.setContentsMargins(SPACE_3, SPACE_4, SPACE_3, SPACE_3)
        job_queue_layout.setSpacing(SPACE_2)
        job_queue_layout.addWidget(self.queue_table)
        self.selected_job_message = QLabel("No jobs have been submitted.")
        self.selected_job_message.setObjectName("selectedJobMessage")
        self.selected_job_message.setWordWrap(True)
        self.selected_job_output = QLabel()
        self.selected_job_output.setObjectName("selectedJobOutput")
        self.selected_job_output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.selected_job_output.setWordWrap(True)
        self.selected_job_stage_progress = QProgressBar()
        self.selected_job_stage_progress.setObjectName("selectedJobStageProgress")
        self.selected_job_stage_progress.setAccessibleName("Stage progress")
        self.selected_job_stage_progress.setRange(0, 1)
        self.selected_job_stage_progress.setTextVisible(True)
        self.selected_job_overall_progress = QProgressBar()
        self.selected_job_overall_progress.setObjectName("selectedJobOverallProgress")
        self.selected_job_overall_progress.setAccessibleName("Whole job progress")
        self.selected_job_overall_progress.setRange(0, 100)
        self.selected_job_overall_progress.setValue(0)
        self.selected_job_overall_progress.setFormat("Whole job: 0%")
        self.move_job_up_button = QPushButton("Move Up")
        self.move_job_up_button.setObjectName("moveJobUpButton")
        self.move_job_down_button = QPushButton("Move Down")
        self.move_job_down_button.setObjectName("moveJobDownButton")
        self.cancel_selected_job_button = QPushButton("Cancel Job")
        self.cancel_selected_job_button.setObjectName("cancelSelectedJobButton")
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
        details_layout.addRow("Message", self.selected_job_message)
        details_layout.addRow("Output", self.selected_job_output)

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
        monitoring_layout.addWidget(self.selected_job_overall_progress)
        monitoring_layout.addWidget(self.selected_job_stage_progress)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(SPACE_2)
        controls.addWidget(self.move_job_up_button)
        controls.addWidget(self.move_job_down_button)
        controls.addStretch(1)
        controls.addWidget(self.cancel_selected_job_button)
        monitoring_layout.addLayout(controls)

        self.view_stack = QStackedWidget()
        self.view_stack.setObjectName("contentViewStack")
        self.view_stack.addWidget(creation_page)
        self.view_stack.addWidget(monitoring_page)
        self.navigation_rail = QWidget()
        self.navigation_rail.setObjectName("viewNavigationRail")
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
        self.message_widget.setObjectName("sessionMessageWidget")
        self.message_tabs = self.message_widget.tabs
        self.global_messages = self.message_widget.global_messages
        self.job_messages = self.message_widget.job_messages
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("contentMessageSplitter")
        splitter.addWidget(content)
        splitter.addWidget(self.message_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        self.setCentralWidget(splitter)

        self.queue_table.selectionModel().currentChanged.connect(self._selection_changed)
        self.queue_table.clicked.connect(self._handle_queue_cell_click)
        model.dataChanged.connect(self._refresh_after_model_change)
        model.rowsInserted.connect(self._select_first_inserted_job)
        model.modelReset.connect(self._refresh_selected_job)
        model.snapshot_changed.connect(self._handle_queue_snapshot)
        self.cancel_selected_job_button.clicked.connect(self._cancel_selected_job)
        self.move_job_up_button.clicked.connect(lambda: self._move_selected_job(-1))
        self.move_job_down_button.clicked.connect(lambda: self._move_selected_job(1))
        self.preferences_action.triggered.connect(self._open_preferences)
        self.editor.inputs.currentRowChanged.connect(self._update_preview_for_source_selection)
        self.editor.inputs.model().rowsInserted.connect(lambda *_: self._update_preview_for_source_selection(self.editor.inputs.currentRow()))
        self.editor.inputs.model().rowsRemoved.connect(lambda *_: self._update_preview_for_source_selection(self.editor.inputs.currentRow()))
        self.source_preview.previous_requested.connect(lambda: self._move_source_selection(-1))
        self.source_preview.next_requested.connect(lambda: self._move_source_selection(1))
        self.source_preview.first_frame_requested.connect(self.source_preview.go_to_first_frame)
        self.source_preview.last_frame_requested.connect(self.source_preview.go_to_last_frame)
        self.source_preview.preview_error.connect(self._append_global_message)
        self.source_preview.audio_preferences_changed.connect(self._audio_preferences_changed)
        self.source_preview.fullscreen_requested.connect(self.source_preview.open_fullscreen)
        self.editor.fullscreen_requested.connect(self._open_source_fullscreen)
        self.editor.message.connect(self._append_global_message)
        self._append_global_message("Application started.")
        self._append_global_message("Add clips in order they should be concatenated.")
        if submission is not None:
            self.editor.request_ready.connect(submission.start)
            submission.busy_changed.connect(self.editor.set_busy)
            submission.status_changed.connect(self._append_global_message)
            submission.queued.connect(lambda job_id: self._append_job_message(job_id, "Job queued."))
            submission.queued.connect(self.editor.job_queued)
            submission.settings_changed.connect(self._apply_settings)
            submission.busy_changed.connect(lambda busy: self._append_global_message("Preflight started." if busy else "Preflight finished."))
        if tool_validator is not None:
            tool_validator.succeeded.connect(self._report_validated_tools)
            tool_validator.failed.connect(lambda _overrides, message: self._append_global_message(f"External-tool validation failed: {message}"))
        self._refresh_selected_job()

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
    def _update_preview_for_source_selection(self, row: int) -> None:
        """Bind preview identity to editor selection only."""

        paths = self.editor.input_paths()
        self.source_preview.set_sources(paths, row)

    @Slot(int)
    def _open_source_fullscreen(self, row: int) -> None:
        """Select a source row and open its fullscreen preview."""

        if 0 <= row < self.editor.inputs.count():
            self.editor.inputs.setCurrentRow(row)
            self.source_preview.open_fullscreen()

    def _queued_source_paths(self) -> tuple[Path, ...]:
        """Return source paths referenced by jobs that still occupy the queue."""

        active_states = {JobState.QUEUED, JobState.VALIDATING, JobState.RUNNING, JobState.CANCELLING}
        paths: list[Path] = []
        for row in range(self._model.rowCount()):
            snapshot = self._model.snapshot_at(self._model.index(row, 0))
            if snapshot is not None and snapshot.state in active_states:
                paths.extend(snapshot.request.inputs)
        return tuple(paths)

    def _move_source_selection(self, offset: int) -> None:
        """Navigate source selection without changing concat order."""

        self._select_source_row(self.editor.inputs.currentRow() + offset)

    def _select_source_row(self, row: int) -> None:
        """Select one existing source row and leave the ordered list intact."""

        if 0 <= row < self.editor.inputs.count():
            self.editor.inputs.setCurrentRow(row)

    def _append_global_message(self, text: str) -> None:
        self.message_widget.append(MessageEvent(text))

    def _append_job_message(self, job_id: str, text: str) -> None:
        self.message_widget.append(MessageEvent(text, job_id))

    @Slot(object, object)
    def _report_validated_tools(self, _overrides: object, toolchain: object) -> None:
        """Publish resolved tool paths without exposing command lines."""

        if not isinstance(toolchain, Toolchain):
            self._append_global_message("External tools validated, but no resolved toolchain was returned.")
            return
        self._append_global_message("External tools validated: " f"FFmpeg {toolchain.ffmpeg.path}; FFprobe {toolchain.ffprobe.path}; " f"Real-ESRGAN {toolchain.realesrgan.path}; models {toolchain.model_directory}.")

    def _append_upscale_progress_summary(self, job_id: str, progress: object) -> None:
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
            self._append_job_message(job_id, f"Upscale progress: {percent}% ({completed}/{total} frames).")
            self._last_upscale_message_percent[job_id] = percent

    @Slot(object)
    def _handle_queue_snapshot(self, snapshot: object) -> None:
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
            self._append_job_message(job_id, f"Job started: {name}." if state is JobState.RUNNING else "Job queued.")
        elif previous_state is not state:
            self._append_job_message(job_id, f"Job {state.value.replace('_', ' ')}.")
        previous_progress = getattr(previous, "last_progress", None)
        if progress is not None and (previous_progress is None or (progress.stage, progress.message) != (previous_progress.stage, previous_progress.message)):
            if progress.stage is PipelineStage.UPSCALE:
                self._append_upscale_progress_summary(job_id, progress)
            else:
                self._append_job_message(job_id, f"{progress.stage.value}: {progress.message}")
        if state is JobState.COMPLETED and getattr(previous, "state", None) is not JobState.COMPLETED:
            name = snapshot.request.generated_output_basename or snapshot.request.explicit_output_path or job_id
            self._append_global_message(f"Job completed: {name}.")
        self._last_snapshots[job_id] = snapshot

    @Slot(QModelIndex, QModelIndex)
    def _selection_changed(self, _current: QModelIndex, _previous: QModelIndex) -> None:
        self._refresh_selected_job(activate_job_tab=True)

    @Slot(QModelIndex)
    def _handle_queue_cell_click(self, index: QModelIndex) -> None:
        """Handle the terminal-row Remove action in the queue table."""

        if index.column() == 2:
            self._model.remove(index)

    @Slot(QModelIndex, QModelIndex, list)
    def _refresh_after_model_change(self, _first: QModelIndex, _last: QModelIndex, _roles: list[int]) -> None:
        self._refresh_selected_job()

    @Slot(QModelIndex, int, int)
    def _select_first_inserted_job(self, _parent: QModelIndex, first: int, _last: int) -> None:
        if not self.queue_table.currentIndex().isValid():
            self.queue_table.setCurrentIndex(self._model.index(first, 0))
        self._refresh_selected_job()

    def _clear_selection_details(self) -> None:
        """Render the empty queue-selection state and disable job actions."""

        self.selected_job_message.setText("No jobs have been submitted.")
        self.selected_job_output.clear()
        self.selected_job_stage_progress.setRange(0, 1)
        self.selected_job_stage_progress.setValue(0)
        self.selected_job_stage_progress.setFormat("Stage: no job selected")
        self.selected_job_overall_progress.setValue(0)
        self.selected_job_overall_progress.setFormat("Whole job: 0%")
        self.cancel_selected_job_button.setEnabled(False)
        self.move_job_up_button.setEnabled(False)
        self.move_job_down_button.setEnabled(False)
        self.job_name_value.setText("No job selected")
        self.job_state_value.setText("No job selected")
        self.job_stage_value.setText("No job selected")
        self.message_widget.select_job(None)

    def _update_progress_details(self, state: object, stage: object, completed: int, total: object) -> None:
        """Render stage and whole-job progress from typed queue roles."""

        # A cancellation snapshot can retain the last pipeline progress event.
        # That value describes work before cancellation, not cancellation or
        # cleanup itself, so do not present it as current job progress.
        if state == JobState.CANCELLING.value:
            self.selected_job_overall_progress.setRange(0, 0)
            self.selected_job_overall_progress.setFormat("Whole job: Cancelling…")
            self.selected_job_stage_progress.setRange(0, 0)
            self.selected_job_stage_progress.setFormat("Stage: Cancelling and cleaning up…")
            return
        if state == JobState.CANCELLED.value:
            self.selected_job_overall_progress.setRange(0, 100)
            self.selected_job_overall_progress.setValue(0)
            self.selected_job_overall_progress.setFormat("Whole job: Cancelled")
            self.selected_job_stage_progress.setRange(0, 1)
            self.selected_job_stage_progress.setValue(0)
            self.selected_job_stage_progress.setFormat("Stage: Cancelled")
            return

        if state == JobState.COMPLETED.value:
            whole_percent = 100
        elif stage is None:
            whole_percent = 0
        else:
            stage_index = tuple(item.value for item in PipelineStage).index(str(stage))
            stage_fraction = completed / max(1, int(total)) if total is not None else 0.0
            whole_percent = min(99, int(((stage_index + stage_fraction) / len(PipelineStage)) * 100))
        self.selected_job_overall_progress.setValue(whole_percent)
        self.selected_job_overall_progress.setFormat(f"Whole job: {whole_percent}%")
        if total is None:
            self.selected_job_stage_progress.setRange(0, 0)
            self.selected_job_stage_progress.setFormat(f"Stage: {stage or 'Working'} (measuring…)")
        else:
            self.selected_job_stage_progress.setRange(0, max(1, int(total)))
            self.selected_job_stage_progress.setValue(completed)
            self.selected_job_stage_progress.setFormat(f"Stage: {completed}/{total}")

    def _render_selection_details(self, index: QModelIndex, *, activate_job_tab: bool) -> None:
        """Render labels, progress, actions, and messages for one selected row."""

        message = self._model.data(index, int(JobRole.ERROR)) or self._model.data(index, int(JobRole.MESSAGE))
        self.selected_job_message.setText(str(message))
        self.selected_job_output.setText(str(self._model.data(index, int(JobRole.OUTPUT_PATH))))
        self.job_name_value.setText(str(self._model.data(self._model.index(index.row(), 1), int(Qt.ItemDataRole.DisplayRole))))
        state = self._model.data(index, int(JobRole.STATE))
        stage = self._model.data(index, int(JobRole.STAGE))
        self.job_state_value.setText(str(state).replace("_", " ").title())
        self.job_stage_value.setText(str(stage or "Waiting"))
        completed = int(self._model.data(index, int(JobRole.PROGRESS_COMPLETED)) or 0)
        total = self._model.data(index, int(JobRole.PROGRESS_TOTAL))
        self._update_progress_details(state, stage, completed, total)
        self.cancel_selected_job_button.setEnabled(bool(self._model.data(index, int(JobRole.CAN_CANCEL))))
        position = self._model.data(index, int(JobRole.QUEUE_POSITION))
        self.move_job_up_button.setEnabled(position is not None and int(position) > 0)
        self.move_job_down_button.setEnabled(position is not None and int(position) + 1 < self._model.pending_count)
        self.message_widget.select_job(str(self._model.data(index, int(JobRole.JOB_ID))), activate=activate_job_tab)

    @Slot()
    def _refresh_selected_job(self, *, activate_job_tab: bool = False) -> None:
        index = self.queue_table.currentIndex()
        if not index.isValid():
            self._clear_selection_details()
            return
        self._render_selection_details(index, activate_job_tab=activate_job_tab)

    @Slot()
    def _cancel_selected_job(self) -> None:
        self._model.cancel(self.queue_table.currentIndex())

    def _move_selected_job(self, offset: int) -> None:
        self._model.move_pending(self.queue_table.currentIndex(), offset)

    @Slot()
    def _open_preferences(self) -> None:
        if self._tool_validator is None or self._settings_store is None:
            return
        dialog = ToolSettingsDialog(self._settings, self._tool_validator, self._settings_store, self)
        dialog.settings_saved.connect(self._apply_settings)
        dialog.exec()

    @Slot(object)
    def _apply_settings(self, value: object) -> None:
        if isinstance(value, ApplicationSettings):
            self._settings = value
            self.editor.apply_settings(value)
            self.source_preview.set_audio_preferences(value.preview_muted, value.preview_volume)
            if self._submission is not None:
                self._submission.apply_settings(value)
            self._append_global_message("Application settings updated.")

    @Slot(bool, int)
    def _audio_preferences_changed(self, muted: bool, volume: int) -> None:
        """Persist only non-safety preview audio preferences."""

        updated = replace(self._settings, preview_muted=muted, preview_volume=volume)
        if self._settings_store is not None:
            try:
                self._settings_store.save(updated)
            except SettingsError as error:
                self._append_global_message(f"Preview audio preferences could not be saved: {error}")
                return
        self._settings = updated

    def closeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Record session shutdown before Qt releases the window."""
        self.source_preview.shutdown()
        if not self._global_shutdown_recorded:
            self._append_global_message("Application shutting down.")
            self._global_shutdown_recorded = True
        super().closeEvent(event)  # type: ignore[arg-type]
